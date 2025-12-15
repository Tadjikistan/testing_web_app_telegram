import asyncio
import inspect
import os

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, time

import aiofiles
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.config import load_settings
from app import db

settings = load_settings()
bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()
dp = Dispatcher()
dp.include_router(router)

# ===== FSM States =====
class AddPromo(StatesGroup):
    preview_image = State()
    title = State()
    description = State()
    link = State()
    confirm = State()


class EditPromo(StatesGroup):
    promo_id = State()
    field = State()
    new_value = State()


class DeletePromo(StatesGroup):
    promo_id = State()


# ===== Helper Functions =====
def is_admin(user_id: int) -> bool:
    return user_id == settings.admin_id


def admin_only(func):
    sig = inspect.signature(func)
    func_params = sig.parameters

    async def wrapper(event, *args, **kwargs):
        filtered_kwargs = {
            name: value for name, value in kwargs.items() if name in func_params
        }
        user_id = event.from_user.id
        if not is_admin(user_id):
            if isinstance(event, CallbackQuery):
                await event.answer("Admins only", show_alert=True)
            else:
                await event.answer("Admins only.")
            return
        return await func(event, *args, **filtered_kwargs)

    return wrapper


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


# ===== Bot Handlers =====
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    web_app_url = os.getenv("WEB_APP_URL")
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Открыть приложение", web_app=WebAppInfo(url=web_app_url))]
        ]
     )
    
    await message.answer(
        text="Добро пожаловать! Нажмите кнопку, чтобы открыть приложение и выбрать подарок.",
        reply_markup=inline_kb
    )

    if is_admin(message.from_user.id):
        admin_kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛠 Admin panel"), KeyboardButton(text="📊 Statistics")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Админ панель"
        )
    
        await message.answer(
            text="Админ-панель активирована 👇", 
            reply_markup=admin_kb
        )


@router.message(F.text == "🛠 Admin panel")
@admin_only
async def open_admin_panel(message: Message):
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add promotion", callback_data="admin:add_promo")],
            [InlineKeyboardButton(text="✏️ Edit promotion", callback_data="admin:edit_promo")],
            [InlineKeyboardButton(text="🗑 Delete promotion", callback_data="admin:del_promo")],
        ]
    )
    await message.answer("Admin panel:", reply_markup=markup)


@router.message(F.text == "📊 Statistics")
@admin_only
async def stats(message: Message):
    data = await db.stats(settings.db_path)
    lines = [f"📊 Statistics", f"New users today: {data['new_users']}"]
    lines.append("\nRedirect clicks:")
    for title, cnt in data["redirect_clicks"]:
        lines.append(f"- {title}: {cnt}")
    lines.append("\n<b>👀 Card Views (All time):</b>")
    if data["view_clicks"]:
        for title, cnt in data["view_clicks"]:
            lines.append(f"- {title}: {cnt}")
    await message.answer("\n".join(lines))


# ===== Admin: Add Promotion =====
@router.callback_query(F.data == "admin:add_promo")
@admin_only
async def admin_add_promo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddPromo.preview_image)
    await callback.message.answer("Send preview image for the card (photo). You can skip with /skip.")
    await callback.answer()


@router.message(AddPromo.preview_image, F.photo)
@admin_only
async def addpromo_preview_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(preview_image_file_id=file_id)
    await state.set_state(AddPromo.title)
    await message.answer("Send promotion title:")


@router.message(AddPromo.preview_image, F.text == "/skip")
@admin_only
async def addpromo_skip_preview_image(message: Message, state: FSMContext):
    await state.update_data(preview_image_file_id=None)
    await state.set_state(AddPromo.title)
    await message.answer("Send promotion title:")


@router.message(AddPromo.title)
@admin_only
async def addpromo_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddPromo.description)
    await message.answer("Send promotion description:")


@router.message(AddPromo.description)
@admin_only
async def addpromo_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddPromo.link)
    await message.answer("Send promotion link (URL):")


@router.message(AddPromo.link)
@admin_only
async def addpromo_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text.strip())
    data = await state.get_data()
    preview = f"<b>{data['title']}</b>\n\n{data['description']}\n\n{data['link']}"
    await state.set_state(AddPromo.confirm)
    await message.answer(
        "Preview:\n" + preview,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Publish", callback_data="admin:add_promo:yes"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data="admin:add_promo:no"),
                ]
            ]
        ),
    )


@router.callback_query(AddPromo.confirm, F.data == "admin:add_promo:yes")
@admin_only
async def addpromo_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    # Duplicate title and preview_image to image_file_id (for modal)
    promo_id = await db.add_promotion(
        settings.db_path,
        title=data["title"],
        description=data["description"],
        link=data["link"],
        preview_image_file_id=data.get("preview_image_file_id"),
        image_file_id=data.get("preview_image_file_id"),  # Duplicate from preview
    )
    await callback.message.answer(f"Promotion #{promo_id} published.")
    await state.clear()
    await callback.answer()


@router.callback_query(AddPromo.confirm, F.data == "admin:add_promo:no")
@admin_only
async def addpromo_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Canceled.")
    await callback.answer()


# ===== Admin: Edit Promotion =====
@router.callback_query(F.data == "admin:edit_promo")
@admin_only
async def admin_edit_promo(callback: CallbackQuery, state: FSMContext):
    promotions = await db.list_promotions(settings.db_path)
    if not promotions:
        await callback.answer("No promotions", show_alert=True)
        return
    rows = []
    for promo in promotions:
        promo_id, title, *_ = promo
        rows.append([InlineKeyboardButton(text=title, callback_data=f"admin_edit_promo:{promo_id}")])
    await state.set_state(EditPromo.promo_id)
    await callback.message.answer("Choose promotion:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(EditPromo.promo_id, F.data.startswith("admin_edit_promo:"))
@admin_only
async def editpromo_choose_promo(callback: CallbackQuery, state: FSMContext):
    promo_id = int(callback.data.split(":")[1])
    await state.update_data(promo_id=promo_id)
    await state.set_state(EditPromo.field)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Preview Image", callback_data="admin:edit_field:preview_image_file_id"),
                InlineKeyboardButton(text="Title", callback_data="admin:edit_field:title"),
            ],
            [
                InlineKeyboardButton(text="Description", callback_data="admin:edit_field:description"),
                InlineKeyboardButton(text="Modal Image", callback_data="admin:edit_field:image_file_id"),
            ],
            [InlineKeyboardButton(text="Link", callback_data="admin:edit_field:link")],
        ]
    )
    await callback.message.answer("What do you want to change?", reply_markup=markup)
    await callback.answer()


@router.callback_query(EditPromo.field, F.data.startswith("admin:edit_field:"))
@admin_only
async def editpromo_choose_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[2]
    await state.update_data(field=field)
    await state.set_state(EditPromo.new_value)
    field_name = {
        "preview_image_file_id": "preview image",
        "title": "title",
        "description": "description",
        "image_file_id": "modal image",
        "link": "link"
    }.get(field, field)
    await callback.message.answer(f"Send new {field_name}:")
    await callback.answer()


@router.message(EditPromo.new_value, F.photo)
@admin_only
async def editpromo_new_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("field")
    if field not in ("image_file_id", "preview_image_file_id"):
        await message.answer("Send text value.")
        return
    file_id = message.photo[-1].file_id
    await db.update_promotion_field(settings.db_path, data["promo_id"], field, file_id)
    await message.answer("Promotion updated.")
    await state.clear()


@router.message(EditPromo.new_value)
@admin_only
async def editpromo_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("field")
    if not field:
        await message.answer("Field is not selected.")
        return
    await db.update_promotion_field(settings.db_path, data["promo_id"], field, message.text.strip())
    await message.answer("Promotion updated.")
    await state.clear()


# ===== Admin: Delete Promotion =====
@router.callback_query(F.data == "admin:del_promo")
@admin_only
async def admin_delete_promo(callback: CallbackQuery, state: FSMContext):
    promotions = await db.list_promotions(settings.db_path)
    if not promotions:
        await callback.answer("No promotions", show_alert=True)
        return
    await state.set_state(DeletePromo.promo_id)
    rows = []
    for promo in promotions:
        promo_id, title, *_ = promo
        rows.append([InlineKeyboardButton(text=title, callback_data=f"admin_delpromo_promo:{promo_id}")])
    await callback.message.answer("Choose promotion:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(DeletePromo.promo_id, F.data.startswith("admin_delpromo_promo:"))
@admin_only
async def deletepromo_choose(callback: CallbackQuery, state: FSMContext):
    promo_id = int(callback.data.split(":")[1])
    await state.update_data(promo_id=promo_id)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=f"del_promo:yes:{promo_id}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"del_promo:no:{promo_id}"),
            ]
        ]
    )
    await callback.message.answer("Confirm deletion?", reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("del_promo:"))
@admin_only
async def deletepromo_confirm(callback: CallbackQuery, state: FSMContext):
    _, decision, promo_id = callback.data.split(":")
    if decision == "yes":
        await db.delete_promotion(settings.db_path, int(promo_id))
        await callback.message.answer("Promotion deleted.")
    else:
        await callback.message.answer("Canceled.")
    await state.clear()
    await callback.answer()

async def update_google_sheet():
    """Функция обновления таблицы (запускается раз в сутки)"""
    try:
        # Получаем данные из БД за вчера
        stats_data = await db.get_daily_stats_for_export(settings.db_path)
        
        # Подключаемся к Google (делаем это в executor, т.к. gspread синхронный)
        def _sync_update():
            scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE")
            GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
            creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scope=scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
            
            # Проверяем заголовки, если таблица пустая
            if not sheet.get_all_values():
                sheet.append_row(["Date", "New Users", "Redirect Clicks", "Promotion Clicks (Views)"])
            
            # Добавляем строку: Date | New Users | Redirects | Promo Clicks
            row = [
                stats_data["date"],
                stats_data["new_users"],
                stats_data["redirect_clicks"],
                stats_data["promotion_clicks"]
            ]
            sheet.append_row(row)
            return row

        # Запускаем синхронный код в отдельном потоке, чтобы не блокировать бота
        loop = asyncio.get_running_loop()
        row_added = await loop.run_in_executor(None, _sync_update)
        print(f"✅ Google Sheet updated: {row_added}")
        
    except Exception as e:
        print(f"❌ Error updating Google Sheet: {e}")

async def scheduler_task():
    """Фоновая задача, проверяющая время"""
    print("⏳ Scheduler started...")
    while True:
        now = datetime.now()
        # Устанавливаем время отправки отчета (например, 00:05 каждый день)
        target_time = time(0, 5) 
        
        # Если время совпадает (с допуском), запускаем
        if now.time().hour == target_time.hour and now.time().minute == target_time.minute:
            await update_google_sheet()
            await asyncio.sleep(65) # Ждем больше минуты, чтобы не запустить дважды
        
        await asyncio.sleep(30) # Проверяем каждые 30 сек

async def main() -> None:
    await db.init_db(settings.db_path)
    
    # Start web server (runs in background)
    web_runner = await init_web_server()
    
    print("Web app is running. Press Ctrl+C to stop.")
    print("Bot is ready for admin commands.")
    
    asyncio.create_task(scheduler_task())
    # Start bot polling (this will block, but web server continues running)
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await web_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
