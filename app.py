import io
import json
import re
import sqlite3

import pandas as pd
import streamlit as st
from openai import OpenAI

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="M.Video Economics", layout="wide")
DEFAULT_COMMISSION_RATE = 0.20


# ══════════════════════════════════════════════════════════════
# COMMISSIONS
# ══════════════════════════════════════════════════════════════
@st.cache_data
def load_commissions() -> pd.DataFrame:
    try:
        df = pd.read_csv(
            "https://raw.githubusercontent.com/krutizmi-cpu/mvideo/main/commissions.csv",
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
        )
        df["Комиссия"] = df["Комиссия"].str.replace(",", ".").astype(float) / 100
        for col in ["Подкатегория", "Планнейм", "Группа Товаров"]:
            df[col] = df[col].fillna("").str.strip()
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки коиссий: {e}")
        return pd.DataFrame(
            columns=["Подкатегория", "Планнейм", "Группа Товаров", "Комиссия"]
        )


commission_df = load_commissions()
commissions_list = commission_df.to_dict("records")


# ══════════════════════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════════════════════
@st.cache_resource
def init_db():
    conn = sqlite3.connect("mvideo.db", check_same_thread=False)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_cache (
            name TEXT PRIMARY KEY,
            category TEXT
        )
    """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            name TEXT NOT NULL,
            cost REAL NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            logistics REAL NOT NULL DEFAULT 0,
            logistics_type TEXT NOT NULL DEFAULT '',
            commission_rate REAL NOT NULL,
            commission_level TEXT NOT NULL,
            commission_key TEXT NOT NULL,
            margin REAL NOT NULL DEFAULT 0,
            profit REAL NOT NULL DEFAULT 0,
            target_margin REAL NOT NULL DEFAULT 0,
            rec_price REAL NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Миграции для старой структуры
    c.execute("PRAGMA table_info(products)")
    cols = {row[1] for row in c.fetchall()}
    to_add = {
        "sku": "TEXT",
        "logistics": "REAL NOT NULL DEFAULT 0",
        "logistics_type": "TEXT NOT NULL DEFAULT ''",
        "margin": "REAL NOT NULL DEFAULT 0",
        "profit": "REAL NOT NULL DEFAULT 0",
        "target_margin": "REAL NOT NULL DEFAULT 0",
        "rec_price": "REAL NOT NULL DEFAULT 0",
        "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
    }
    for col, ddl in to_add.items():
        if col not in cols:
            c.execute(f"ALTER TABLE products ADD COLUMN {col} {ddl}")

    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products(sku)")
    conn.commit()
    return conn


conn = init_db()


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def normalize_text(value: str) -> str:
    value = (value or "").lower().strip()
    value = value.replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def token_overlap_score(left: str, right: str) -> float:
    left_tokens = set(normalize_text(left).split())
    right_tokens = set(normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(right_tokens), 1)


def get_openai_api_key(manual_key: str = "") -> str:
    if manual_key and manual_key.strip():
        return manual_key.strip()
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


def get_progress_bounds(series: pd.Series) -> tuple[float, float]:
    cleaned = series.dropna()
    if cleaned.empty:
        return 0.0, 1.0

    min_value = float(cleaned.min())
    max_value = float(cleaned.max())

    if min_value == max_value:
        delta = max(abs(min_value) * 0.01, 1.0)
        min_value -= delta
        max_value += delta

    return min_value, max_value


def find_row_by_category_name(category_name: str):
    category_name_norm = normalize_text(category_name)
    if not category_name_norm:
        return None

    for row in commissions_list:
        for key in ["Группа Товаров", "Планнейм", "Подкатегория"]:
            if normalize_text(row[key]) == category_name_norm:
                return row, key, row[key]
    return None


def is_accessory_bike_mismatch(product_name: str, category_name: str) -> bool:
    product = normalize_text(product_name)
    category = normalize_text(category_name)

    is_bike = "велосипед" in product
    looks_like_full_bike = (
        is_bike
        and "рама" not in product
        and "запчаст" not in product
        and "аксесс" not in product
        and "креплен" not in product
    )

    accessory_words = ["рама", "креплен", "для авто", "багажн", "аксесс", "запчаст"]
    if looks_like_full_bike and any(w in category for w in accessory_words):
        return True

    if "авто" not in product and "для авто" in category:
        return True

    return False


def ai_match_category(name: str, api_key: str):
    categories = sorted(
        {
            row[field].strip()
            for row in commissions_list
            for field in ["Группа Товаров", "Планнейм", "Подкатегория"]
            if row[field].strip()
        }
    )
    if not categories:
        return None

    prompt = (
        "Выбери ОДНУ лучшую категорию из списка для названия товара. "
        "Если подходящей категории нет, ответь NONE. "
        "Важно: если товар — полноценный велосипед, не выбирай категории для авто-креплений и запчастей. "
        "Ответ строго JSON: {\"category\":\"...\"}.\n\n"
        f"Название товара: {name}\n\n"
        "Список категорий:\n"
        + "\n".join(f"- {c}" for c in categories)
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(model="gpt-4o-mini", input=prompt, temperature=0)
        payload = json.loads(response.output_text)
        selected = str(payload.get("category", "")).strip()
        if not selected or selected.upper() == "NONE":
            return None
        return selected
    except Exception:
        return None


def find_commission(name: str, openai_key: str = "") -> tuple[float, str, str]:
    if not name or name == "Неизвестно":
        return DEFAULT_COMMISSION_RATE, "Others (дефолт)", "Others"

    name_norm = normalize_text(name)

    # 1) Прямое вхождение
    for field in ["Группа Товаров", "Планнейм", "Подкатегория"]:
        for row in commissions_list:
            category = row[field]
            cat_norm = normalize_text(category)
            if cat_norm and (cat_norm in name_norm or name_norm in cat_norm):
                if is_accessory_bike_mismatch(name, category):
                    continue
                return row["Комиссия"], field, category

    # 2) Fuzzy
    best = None
    for field in ["Группа Товаров", "Планнейм", "Подкатегория"]:
        for row in commissions_list:
            category = row[field]
            score = token_overlap_score(name, category)
            if score < 0.6:
                continue
            if is_accessory_bike_mismatch(name, category):
                continue
            if best is None or score > best[0]:
                best = (score, row, field, category)

    if best:
        _, row, field, category = best
        return row["Комиссия"], f"{field} (fuzzy)", category

    # 3) AI fallback (кэш -> запрос -> кэш)
    api_key = get_openai_api_key(openai_key)
    if api_key:
        c = conn.cursor()
        c.execute("SELECT category FROM ai_cache WHERE name = ?", (name,))
        cached = c.fetchone()
        if cached:
            found = find_row_by_category_name(cached[0])
            if found and not is_accessory_bike_mismatch(name, cached[0]):
                row, field, label = found
                return row["Комиссия"], f"AI Cache ({field})", label

        ai_category = ai_match_category(name, api_key)
        if ai_category and not is_accessory_bike_mismatch(name, ai_category):
            found = find_row_by_category_name(ai_category)
            if found:
                row, field, label = found
                c.execute(
                    "INSERT OR REPLACE INTO ai_cache (name, category) VALUES (?, ?)",
                    (name, ai_category),
                )
                conn.commit()
                return row["Комиссия"], f"AI Match ({field})", label

    return DEFAULT_COMMISSION_RATE, "Others (дефолт)", "Others"


def calculate_logistics(l, w, h, weight):
    """
    Габариты приходят в сантиметрах.

    Тарифы:
    - S: 110 ₽
    - M: 190 ₽
    - L/XL: 1290 ₽

    Логика классов:
    - XL: любая сторона > 120 см
    - L: объем > 0.2 м3 или > 200 л или вес > 15 кг
    - M: объем >= 0.01 м3 или >= 10 л
    - S: остальное
    """
    l = max(float(l), 0.0)
    w = max(float(w), 0.0)
    h = max(float(h), 0.0)
    weight = max(float(weight), 0.0)

    volume_m3 = (l * w * h) / 1_000_000
    volume_liters = (l * w * h) / 1000
    max_side = max(l, w, h)

    if max_side > 120:
        return 1290, "Негабарит (XL)"
    if volume_m3 > 0.2 or volume_liters > 200 or weight > 15:
        return 1290, "Крупногабаритный (L)"
    if volume_m3 >= 0.01 or volume_liters >= 10:
        return 190, "Среднегабаритный (M)"
    return 110, "Малогабаритный (S)"


def calculate_tax(price, cost, logistics, commission, acq, early, tax_system):
    if tax_system == "УСН Доходы (6%)":
        return price * 0.06
    if tax_system == "Самозанятый (4%)":
        return price * 0.04
    if tax_system == "ОСНО (20%)":
        return price * 0.20
    if tax_system == "УСН Доходы-Расходы (15%)":
        expenses = cost + logistics + commission + acq + early
        profit_before_tax = price - expenses
        return max(0, profit_before_tax * 0.15)
    return 0


def find_target_price(cost, logistics, commission_rate, acq_rate, early_rate, tax_type, target_m):
    m_decimal = target_m / 100
    acq_dec = acq_rate / 100
    early_dec = early_rate / 100

    if tax_type == "УСН Доходы (6%)":
        tax_rate = 0.06
    elif tax_type == "Самозанятый (4%)":
        tax_rate = 0.04
    elif tax_type == "ОСНО (20%)":
        tax_rate = 0.20
    elif tax_type == "УСН Доходы-Расходы (15%)":
        denom = (1 - m_decimal - commission_rate - acq_dec - early_dec) * 0.85
        return 0 if denom <= 0 else (cost + logistics) / denom
    else:
        tax_rate = 0

    denom = 1 - m_decimal - commission_rate - acq_dec - early_dec - tax_rate
    return 0 if denom <= 0 else (cost + logistics) / denom


def save_calculation_to_db(row: dict):
    c = conn.cursor()
    sku = row["Артикул"]

    c.execute(
        """
        INSERT INTO products (
            sku, name, cost, price, stock,
            logistics, logistics_type,
            commission_rate, commission_level, commission_key,
            margin, profit, target_margin, rec_price, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(sku) DO UPDATE SET
            name=excluded.name,
            cost=excluded.cost,
            price=excluded.price,
            stock=excluded.stock,
            logistics=excluded.logistics,
            logistics_type=excluded.logistics_type,
            commission_rate=excluded.commission_rate,
            commission_level=excluded.commission_level,
            commission_key=excluded.commission_key,
            margin=excluded.margin,
            profit=excluded.profit,
            target_margin=excluded.target_margin,
            rec_price=excluded.rec_price,
            updated_at=CURRENT_TIMESTAMP
    """,
        (
            sku,
            row["Наименование"],
            float(row["Себестоимость"]),
            float(row["Тек. Цена"]),
            int(row.get("Остаток", 0)),
            float(row["Логистика"]),
            row["Тип логистики"],
            float(row["Комиссия %"]) / 100,
            row["Уровень"],
            row["Категория"],
            float(row["Маржа %"]),
            float(row["Прибыль"]),
            float(row["Цель Маржа %"]),
            float(row["Рек. Цена"]),
        ),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 10.0, 1.5)
    tax_system = st.selectbox(
        "Налоги",
        ["УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", "ОСНО (20%)", "Самозанятый (4%)"],
    )
    early_payout = st.number_input("Досрочный вывод (%)", 0.0, 10.0, 0.0)
    target_margin = st.number_input("🎯 Целевая маржа (%)", 0.0, 100.0, 20.0)

    st.markdown("---")
    openai_key = st.text_input("OpenAI API Key (опционально)", type="password")

    st.markdown("---")
    st.subheader("📁 Шаблон для загрузки")
    template_df = pd.DataFrame(
        columns=["артикул", "наименование", "д", "ш", "в", "вес", "цена", "себестоимость"]
    )
    template_df.loc[0] = ["SKU-001", "Пример товара", 10, 10, 10, 0.5, 2990, 1500]

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        template_df.to_excel(writer, index=False)

    st.download_button(
        "📥 Скачать шаблон Excel",
        buffer.getvalue(),
        "template.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    uploaded_file = st.file_uploader("Загрузите файл Excel", type=["xlsx"])


# ══════════════════════════════════════════════════════════════
# TITLE + 2 TABS
# ══════════════════════════════════════════════════════════════
st.title("💼 M.Video — Юнит-экономика")
tab1, tab2 = st.tabs(["📦 Массовый расчёт (Excel)", "📋 Все товары"])

st.caption(
    "Работаем только через масовую загрузку Excel. После расчета товар сохраняется по артикулу (SKU): "
    "повторная загрузка того же артикула обновляет запись."
)


# ══════════════════════════════════════════════════════════════
# TAB 1: MASS CALC FROM EXCEL
# ══════════════════════════════════════════════════════════════
with tab1:
    if uploaded_file:
        df_upload = pd.read_excel(uploaded_file)
        df_upload.columns = [str(c).strip().lower() for c in df_upload.columns]
        results = []

        with st.status("🔍 Обработка...") as status:
            for index, row in df_upload.iterrows():
                try:
                    name = str(row.get("наименование", "Неизвестно"))
                    sku = str(row.get("артикул", f"Row-{index}")).strip() or f"Row-{index}"
                    price = float(row.get("цена", 0))
                    cost = float(row.get("себестоимость", 0))
                    l = float(row.get("д", 0))
                    w = float(row.get("ш", 0))
                    h = float(row.get("в", 0))
                    weight = float(row.get("вес", 0))

                    comm_rate, comm_level, comm_key = find_commission(name, openai_key)
                    logistics, logistics_type = calculate_logistics(l, w, h, weight)
                    ref_fee = price * comm_rate
                    acq_cost = price * (acquiring / 100)
                    early_cost = price * (early_payout / 100)
                    tax_cost = calculate_tax(price, cost, logistics, ref_fee, acq_cost, early_cost, tax_system)

                    profit = price - (cost + ref_fee + logistics + acq_cost + early_cost + tax_cost)
                    margin = (profit / price) * 100 if price > 0 else 0
                    rec_price = find_target_price(
                        cost,
                        logistics,
                        comm_rate,
                        acquiring,
                        early_payout,
                        tax_system,
                        target_margin,
                    )

                    result_row = {
                        "Артикул": sku,
                        "Наименование": name,
                        "Себестоимость": round(cost, 2),
                        "Категория": comm_key,
                        "Уровень": comm_level,
                        "Комиссия %": round(comm_rate * 100, 1),
                        "Тек. Цена": round(price, 2),
                        "Логистика": round(logistics, 2),
                        "Тип логистики": logistics_type,
                        "Маржа %": round(margin, 2),
                        "Прибыль": round(profit, 2),
                        "Цель Маржа %": target_margin,
                        "Рек. Цена": round(rec_price, 0),
                        "Остаток": 0,
                    }
                    results.append(result_row)
                    save_calculation_to_db(result_row)

                except Exception as e:
                    st.error(f"Ошибка в строке {index}: {e}")

            status.update(label="✅ Готово! Данные сохранены в «Все товары»", state="complete")

        if results:
            res_df = pd.DataFrame(results)
            margin_min, margin_max = get_progress_bounds(res_df["Маржа %"])
            st.dataframe(
                res_df,
                use_container_width=True,
                column_config={
                    "Маржа %": st.column_config.ProgressColumn(
                        "Маржа %",
                        format="%.2f%%",
                        min_value=margin_min,
                        max_value=margin_max,
                    )
                },
            )

            csv = res_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 Скачать результат CSV", csv, "results.csv", "text/csv")
        else:
            st.warning("Нет данных для отображения.")
    else:
        st.info("Загрузите файл Excel через боковую панель для начала расчёта.")
        st.table(template_df)


# ══════════════════════════════════════════════════════════════
# TAB 2: ALL PRODUCTS (memory by SKU + export)
# ══════════════════════════════════════════════════════════════
with tab2:
    df_products = pd.read_sql_query(
        """
        SELECT
            id,
            sku AS "Артикул",
            name AS "Наименование",
            cost AS "Себестоимость",
            price AS "Тек. Цена",
            logistics AS "Логистика",
            logistics_type AS "Тип логистики",
            ROUND(commission_rate * 100, 1) AS "Комиссия %",
            commission_level AS "Уровень",
            commission_key AS "Категория",
            margin AS "Маржа %",
            profit AS "Прибыль",
            target_margin AS "Цель Маржа %",
            rec_price AS "Рек. Цена",
            updated_at AS "Обновлено"
        FROM products
        ORDER BY id DESC
    """,
        conn,
    )

    if df_products.empty:
        st.info("Товаров пока нет. Загрузите Excel в первой вкладке.")
    else:
        margin_min, margin_max = get_progress_bounds(df_products["Маржа %"])
        st.dataframe(
            df_products,
            use_container_width=True,
            column_config={
                "Маржа %": st.column_config.ProgressColumn(
                    "Маржа %",
                    format="%.2f%%",
                    min_value=margin_min,
                    max_value=margin_max,
                )
            },
        )

        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            df_products.to_excel(writer, index=False, sheet_name="products")

        st.download_button(
            "📥 Скачать все товары (Excel)",
            out.getvalue(),
            "all_products.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.markdown("---")
        del_sku = st.text_input("Удалить товар по артикулу (SKU)")
        if st.button("🗑️ Удалить товар") and del_sku.strip():
            c = conn.cursor()
            c.execute("DELETE FROM products WHERE sku = ?", (del_sku.strip(),))
            conn.commit()
            st.success(f"Товар с артикулом {del_sku.strip()} удалён.")
            st.rerun()
