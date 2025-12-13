import asyncio
import os

import aiofiles
import aiohttp
from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import load_settings
from app import db

settings = load_settings()
# Bot instance only needed for getting file URLs
bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


# ===== Web Server Handlers =====
async def serve_html(request):
    filename = request.match_info.get("filename", "first_card.html")
    filepath = os.path.join(os.path.dirname(__file__), filename)
    
    if not os.path.exists(filepath):
        return web.Response(text="File not found", status=404)
    
    async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
        content = await f.read()
    
    # Inject Telegram WebApp script
    if "telegram-web-app.js" not in content and filename in ("first_card.html", "list_of_card.html"):
        script_tag = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
        content = content.replace("</head>", f"{script_tag}\n</head>")
    
    return web.Response(text=content, content_type="text/html")


async def api_promotions(request):
    """GET /api/promotions - List all promotions"""
    promotions = await db.list_promotions(settings.db_path)
    result = []
    for promo in promotions:
        promo_id, title, description, link, preview_image_file_id, image_file_id = promo
        result.append({
            "id": promo_id,
            "title": title,
            "description": description,
            "link": link,
            "preview_image_file_id": preview_image_file_id,
            "image_file_id": image_file_id,
        })
    return web.json_response({"promotions": result})


async def api_promotion_detail(request):
    """GET /api/promotions/{id} - Get single promotion"""
    promo_id = int(request.match_info["id"])
    promo = await db.get_promotion(settings.db_path, promo_id)
    if not promo:
        return web.json_response({"error": "Not found"}, status=404)
    
    promo_id, title, description, link, preview_image_file_id, image_file_id = promo
    return web.json_response({
        "id": promo_id,
        "title": title,
        "description": description,
        "link": link,
        "preview_image_file_id": preview_image_file_id,
        "image_file_id": image_file_id,
    })


async def api_promotion_click(request):
    """POST /api/promotions/{id}/click - Log promotion click"""
    promo_id = int(request.match_info["id"])
    data = await request.json()
    action = data.get("action", "redirect")
    
    # Get user_id from request data or headers
    user_id = data.get("user_id")
    if not user_id and "X-Telegram-User-Id" in request.headers:
        try:
            user_id = int(request.headers["X-Telegram-User-Id"])
        except (ValueError, TypeError):
            pass
    
    await db.log_promotion_click(settings.db_path, promo_id, action, user_id)
    return web.json_response({"success": True})


async def api_top_promotions(request):
    """GET /api/top-promotions - Get top promotions for HIT marks"""
    top = await db.top_promotions_all_time(settings.db_path, limit=10)
    result = [{"id": promo_id} for promo_id, _ in top]
    return web.json_response(result)


async def api_image_proxy(request):
    """GET /api/image/{file_id} - Proxy Telegram images"""
    file_id = request.match_info["file_id"]
    try:
        file = await bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{settings.bot_token}/{file.file_path}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status == 200:
                    image_data = await resp.read()
                    return web.Response(body=image_data, content_type=resp.headers.get("Content-Type", "image/jpeg"))
                else:
                    return web.Response(status=404)
    except Exception as e:
        print(f"Error getting image: {e}")
        return web.Response(status=404)


# ===== Main =====
async def init_web_server():
    """Initialize web server for HTML files and API"""
    app = web.Application()
    
    # Serve HTML files
    app.router.add_get("/{filename}", serve_html)
    app.router.add_get("/", lambda r: serve_html(r))
    
    # API endpoints
    app.router.add_get("/api/promotions", api_promotions)
    app.router.add_get("/api/promotions/{id}", api_promotion_detail)
    app.router.add_post("/api/promotions/{id}/click", api_promotion_click)
    app.router.add_get("/api/top-promotions", api_top_promotions)
    app.router.add_get("/api/image/{file_id}", api_image_proxy)
    
    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-User-Id"
        return response
    
    app.middlewares.append(cors_middleware)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("WEB_PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    print(f"Web server started on port {port}")
    return runner


async def main() -> None:
    await db.init_db(settings.db_path)
    
    # Start web server
    web_runner = await init_web_server()
    
    print("Web app is running. Press Ctrl+C to stop.")
    
    # Keep the server running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await web_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
