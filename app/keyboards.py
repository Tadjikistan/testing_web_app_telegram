from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu(is_admin: bool, full: bool = True) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="🎁 Claim a gift")]]
    if full:
        buttons.append([KeyboardButton(text="📦 Promotions catalog")])
        buttons.append([KeyboardButton(text="🔥 Promotions of the day"), KeyboardButton(text="🏆 Hit")])
    if is_admin:
        buttons.append(
            [KeyboardButton(text="🛠 Admin panel"), KeyboardButton(text="📊 Statistics")]
        )
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def catalogs_keyboard(catalogs, prefix: str = "catalog"):
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"{prefix}:{catalog_id}")]
        for catalog_id, name in catalogs
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promotions_keyboard(
    promotions,
    catalog_id: int,
    prefix: str = "promo",
    back_callback: str = "back:catalogs",
):
    rows = []
    for promo in promotions:
        promo_id, title, *_ = promo
        rows.append([InlineKeyboardButton(text=title, callback_data=f"{prefix}:{promo_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def promo_actions_keyboard(promo_id: int, link: str, catalog_id: int):
    rows = [
        [
            InlineKeyboardButton(text="🟢 Get discount", url=link),
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"back:catalog:{catalog_id}"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_keyboard():
    rows = [
        [
            InlineKeyboardButton(text="➕ Add catalog", callback_data="admin:add_catalog"),
            InlineKeyboardButton(text="➕ Add promotion", callback_data="admin:add_promo"),
        ],
        [
            InlineKeyboardButton(
                text="✏️ Change catalog name", callback_data="admin:rename_catalog"
            ),
            InlineKeyboardButton(text="✏️ Edit promotion", callback_data="admin:edit_promo"),
        ],
        [
            InlineKeyboardButton(text="🗑 Delete catalog", callback_data="admin:del_catalog"),
            InlineKeyboardButton(text="🗑 Delete promotion", callback_data="admin:del_promo"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(prefix: str, item_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=f"{prefix}:yes:{item_id}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:no:{item_id}"),
            ]
        ]
    )

