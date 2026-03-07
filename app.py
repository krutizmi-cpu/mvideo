import io
import json
import re
import sqlite3
from typing import Optional

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
    def _prepare(df: pd.DataFrame) -> pd.DataFrame:
        df["Комиссия"] = df["Комиссия"].str.replace(",", ".", regex=False).astype(float) / 100
        for col in ["Подкатегория", "Планнейм", "Группа Товаров"]:
            df[col] = df[col].fillna("").str.strip()
        return df

    try:
        remote_df = pd.read_csv(
            "https://raw.githubusercontent.com/krutizmi-cpu/mvideo/main/commissions.csv",
            sep=";",
            encoding="utf-8-sig",
            dtype=str,
        )
        return _prepare(remote_df)
    except Exception as remote_error:
        try:
            local_df = pd.read_csv("commissions.csv", sep=";", encoding="utf-8-sig", dtype=str)
            st.warning("Не удалось загрузить комиссии из GitHub, используется локальный commissions.csv")
            return _prepare(local_df)
        except Exception as local_error:
            st.error(f"Ошибка загрузки комиссий: remote={remote_error}; local={local_error}")
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
            markup REAL NOT NULL DEFAULT 0,
            profit REAL NOT NULL DEFAULT 0,
            full_cost REAL NOT NULL DEFAULT 0,
            rec_margin REAL NOT NULL DEFAULT 0,
            rec_profit REAL NOT NULL DEFAULT 0,
            target_margin REAL NOT NULL DEFAULT 0,
            rec_price REAL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    c.execute("PRAGMA table_info(products)")
    cols = {row[1] for row in c.fetchall()}
    to_add = {
        "sku": "TEXT",
        "logistics": "REAL NOT NULL DEFAULT 0",
        "logistics_type": "TEXT NOT NULL DEFAULT ''",
        "margin": "REAL NOT NULL DEFAULT 0",
        "markup": "REAL NOT NULL DEFAULT 0",
        "profit": "REAL NOT NULL DEFAULT 0",
        "full_cost": "REAL NOT NULL DEFAULT 0",
        "rec_margin": "REAL NOT NULL DEFAULT 0",
        "rec_profit": "REAL NOT NULL DEFAULT 0",
        "target_margin": "REAL NOT NULL DEFAULT 0",
        "rec_price": "REAL",
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



def format_optional_price(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 0)



def normalize_excel_columns(df: pd.DataFrame) -> pd.DataFrame:
    alias_map = {
        "артикул": "артикул",
        "sku": "артикул",
        "наименование": "наименование",
        "название": "наименование",
        "д": "д",
        "д(см)": "д",
        "длина": "д",
        "длина(см)": "д",
        "ш": "ш",
        "ш(см)": "ш",
        "ширина": "ш",
        "ширина(см)": "ш",
        "в": "в",
        "в(см)": "в",
        "высота": "в",
        "высота(см)": "в",
        "вес": "вес",
        "вес(кг)": "вес",
        "масса": "вес",
        "масса(кг)": "вес",
        "цена": "цена",
        "себестоимость": "себестоимость",
    }

    normalized = []
    for col in df.columns:
        c = str(col).lower().replace("ё", "е").strip()
        c = c.replace(" ", "")
        c = alias_map.get(c, c)
        normalized.append(c)

    df = df.copy()
    df.columns = normalized
    return df



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

    for field in ["Группа Товаров", "Планнейм", "Подкатегория"]:
        for row in commissions_list:
            category = row[field]
            cat_norm = normalize_text(category)
            if cat_norm and (cat_norm in name_norm or name_norm in cat_norm):
                if is_accessory_bike_mismatch(name, category):
                    continue
                return row["Комиссия"], field, category

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

    if "велосипед" in name_norm and not any(
        w in name_norm for w in ["рама", "креплен", "запчаст", "аксесс", "для авто"]
    ):
        return DEFAULT_COMMISSION_RATE, "Эвристика (велосипед)", "Велосипед"

    return DEFAULT_COMMISSION_RATE, "Others (дефолт)", "Others"


# ══════════════════════════════════════════════════════════════
# CALCULATIONS
# ══════════════════════════════════════════════════════════════
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



def vat_part(amount: float) -> float:
    return max(0.0, amount) * 20 / 120



def calculate_tax(price, cost, logistics, commission, acq, early, tax_system):
    if tax_system == "УСН Доходы (6%)":
        return price * 0.06

    if tax_system == "Самозанятый (4%)":
        return price * 0.04

    if tax_system == "УСН Доходы-Расходы (15%)":
        expenses = cost + logistics + commission + acq + early
        profit_before_tax = price - expenses
        tax_15 = max(0.0, profit_before_tax * 0.15)
        min_tax = price * 0.01
        return max(tax_15, min_tax)

    if tax_system == "ОСНО (упрощённая, 22%)":
        output_vat = vat_part(price)
        preliminary_profit = price - (cost + logistics + commission + acq + early + output_vat)
        income_tax = max(0.0, preliminary_profit * 0.22)
        return output_vat + income_tax

    if tax_system == "ОСНО (реальная, 22%)":
        output_vat = vat_part(price)
        input_vat = (
            vat_part(cost)
            + vat_part(logistics)
            + vat_part(commission)
            + vat_part(acq)
            + vat_part(early)
        )
        vat_payable = max(0.0, output_vat - input_vat)

        revenue_wo_vat = price - output_vat
        cost_wo_vat = cost - vat_part(cost)
        logistics_wo_vat = logistics - vat_part(logistics)
        commission_wo_vat = commission - vat_part(commission)
        acq_wo_vat = acq - vat_part(acq)
        early_wo_vat = early - vat_part(early)

        profit_before_income_tax = (
            revenue_wo_vat
            - cost_wo_vat
            - logistics_wo_vat
            - commission_wo_vat
            - acq_wo_vat
            - early_wo_vat
        )
        income_tax = max(0.0, profit_before_income_tax * 0.22)
        return vat_payable + income_tax

    return 0.0



def calculate_unit_metrics(
    price: float,
    cost: float,
    logistics: float,
    commission_rate: float,
    acq_rate_percent: float,
    early_rate_percent: float,
    tax_system: str,
) -> dict:
    price = max(float(price), 0.0)
    cost = max(float(cost), 0.0)
    logistics = max(float(logistics), 0.0)
    commission_rate = max(float(commission_rate), 0.0)
    acq_rate_decimal = max(float(acq_rate_percent), 0.0) / 100
    early_rate_decimal = max(float(early_rate_percent), 0.0) / 100

    commission_fee = price * commission_rate
    acquiring_cost = price * acq_rate_decimal
    payout_base = max(0.0, price - commission_fee - logistics - acquiring_cost)
    early_fee = payout_base * early_rate_decimal
    tax_cost = calculate_tax(price, cost, logistics, commission_fee, acquiring_cost, early_fee, tax_system)

    full_cost = cost + logistics + commission_fee + acquiring_cost + early_fee + tax_cost
    profit = price - full_cost

    margin_percent = ((price / full_cost) - 1) * 100 if full_cost > 0 else 0.0
    markup_percent = ((price - full_cost) / full_cost) * 100 if full_cost > 0 else 0.0

    return {
        "commission_fee": commission_fee,
        "acquiring_cost": acquiring_cost,
        "payout_base": payout_base,
        "early_fee": early_fee,
        "tax_cost": tax_cost,
        "full_cost": full_cost,
        "profit": profit,
        "margin_percent": margin_percent,
        "markup_percent": markup_percent,
    }



def find_target_price(cost, logistics, commission_rate, acq_rate, early_rate, tax_type, target_m):
    target_margin_decimal = target_m / 100

    def calc_margin_for_price(candidate_price: float) -> float:
        metrics = calculate_unit_metrics(
            price=candidate_price,
            cost=cost,
            logistics=logistics,
            commission_rate=commission_rate,
            acq_rate_percent=acq_rate,
            early_rate_percent=early_rate,
            tax_system=tax_type,
        )
        return metrics["margin_percent"] / 100

    low = max(cost + logistics, 1.0)
    high = max(low * 2, 1000.0)

    for _ in range(40):
        if calc_margin_for_price(high) >= target_margin_decimal:
            break
        high *= 1.5
    else:
        return None

    for _ in range(80):
        mid = (low + high) / 2
        if calc_margin_for_price(mid) >= target_margin_decimal:
            high = mid
        else:
            low = mid

    return round(high, 2)



def save_calculation_to_db(row: dict):
    c = conn.cursor()
    sku = row["Артикул"]

    c.execute(
        """
        INSERT INTO products (
            sku, name, cost, price, stock,
            logistics, logistics_type,
            commission_rate, commission_level, commission_key,
            margin, markup, profit, full_cost,
            rec_margin, rec_profit,
            target_margin, rec_price, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
            markup=excluded.markup,
            profit=excluded.profit,
            full_cost=excluded.full_cost,
            rec_margin=excluded.rec_margin,
            rec_profit=excluded.rec_profit,
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
            float(row["Маржинальность % (от текущей цены)"]),
            float(row["Наценка % (от текущей цены)"]),
            float(row["Прибыль (от текущей цены)"]),
            float(row["Полная себестоимость (от текущей цены)"]),
            float(row["Маржинальность % (от рек. цены)"]) if row["Маржинальность % (от рек. цены)"] is not None else 0.0,
            float(row["Прибыль (от рек. цены)"]) if row["Прибыль (от рек. цены)"] is not None else 0.0,
            float(row["Целевая маржинальность %"]),
            float(row["Рек. Цена"]) if row["Рек. Цена"] is not None else None,
        ),
    )
    conn.commit()


# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 20.0, 1.5)
    tax_system = st.selectbox(
        "Налоги",
        [
            "УСН Доходы (6%)",
            "УСН Доходы-Расходы (15%)",
            "ОСНО (реальная, 22%)",
            "ОСНО (упрощённая, 22%)",
            "Самозанятый (4%)",
        ],
    )
    early_payout = st.number_input("Досрочный вывод (%)", 0.0, 20.0, 0.0)
    target_margin = st.number_input("🎯 Целевая маржинальность (%)", 0.0, 1000.0, 20.0)

    st.markdown("---")
    openai_key = st.text_input("OpenAI API Key (опционально)", type="password")

    st.markdown("---")
    st.subheader("📁 Шаблон для загрузки")
    template_df = pd.DataFrame(
        columns=["артикул", "наименование", "д (см)", "ш (см)", "в (см)", "вес (кг)", "цена", "себестоимость"]
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
    "Работаем только через массовую загрузку Excel. После расчета товар сохраняется по артикулу (SKU): "
    "повторная загрузка того же артикула обновляет запись."
)


# ══════════════════════════════════════════════════════════════
# TAB 1: MASS CALC FROM EXCEL
# ══════════════════════════════════════════════════════════════
with tab1:
    if uploaded_file:
        df_upload = pd.read_excel(uploaded_file)
        df_upload = normalize_excel_columns(df_upload)
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

                    current_metrics = calculate_unit_metrics(
                        price=price,
                        cost=cost,
                        logistics=logistics,
                        commission_rate=comm_rate,
                        acq_rate_percent=acquiring,
                        early_rate_percent=early_payout,
                        tax_system=tax_system,
                    )

                    rec_price = find_target_price(
                        cost=cost,
                        logistics=logistics,
                        commission_rate=comm_rate,
                        acq_rate=acquiring,
                        early_rate=early_payout,
                        tax_type=tax_system,
                        target_m=target_margin,
                    )

                    rec_metrics = None
                    if rec_price is not None:
                        rec_metrics = calculate_unit_metrics(
                            price=rec_price,
                            cost=cost,
                            logistics=logistics,
                            commission_rate=comm_rate,
                            acq_rate_percent=acquiring,
                            early_rate_percent=early_payout,
                            tax_system=tax_system,
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
                        "Полная себестоимость (от текущей цены)": round(current_metrics["full_cost"], 2),
                        "Маржинальность % (от текущей цены)": round(current_metrics["margin_percent"], 2),
                        "Наценка % (от текущей цены)": round(current_metrics["markup_percent"], 2),
                        "Прибыль (от текущей цены)": round(current_metrics["profit"], 2),
                        "Целевая маржинальность %": float(target_margin),
                        "Рек. Цена": format_optional_price(rec_price),
                        "Маржинальность % (от рек. цены)": round(rec_metrics["margin_percent"], 2) if rec_metrics else None,
                        "Прибыль (от рек. цены)": round(rec_metrics["profit"], 2) if rec_metrics else None,
                        "Остаток": 0,
                    }
                    results.append(result_row)
                    save_calculation_to_db(result_row)

                except Exception as e:
                    st.error(f"Ошибка в строке {index}: {e}")

            status.update(label="✅ Готово! Данные сохранены в «Все товары»", state="complete")

        if results:
            res_df = pd.DataFrame(results)
            margin_min, margin_max = get_progress_bounds(res_df["Маржинальность % (от текущей цены)"])
            st.dataframe(
                res_df,
                use_container_width=True,
                column_config={
                    "Маржинальность % (от текущей цены)": st.column_config.ProgressColumn(
                        "Маржинальность % (от текущей цены)",
                        format="%.2f%%",
                        min_value=margin_min,
                        max_value=margin_max,
                    ),
                    "Маржинальность % (от рек. цены)": st.column_config.NumberColumn(
                        "Маржинальность % (от рек. цены)", format="%.2f%%"
                    ),
                    "Наценка % (от текущей цены)": st.column_config.NumberColumn(
                        "Наценка % (от текущей цены)", format="%.2f%%"
                    ),
                },
            )

            out_res = io.BytesIO()
            with pd.ExcelWriter(out_res, engine="openpyxl") as writer:
                res_df.to_excel(writer, index=False, sheet_name="results")
            st.download_button(
                "📥 Скачать результат Excel",
                out_res.getvalue(),
                "results.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning("Нет данных для отображения.")
    else:
        st.info("Загрузите файл Excel через боковую панель для начала расчёта.")
        st.table(template_df)


# ══════════════════════════════════════════════════════════════
# TAB 2: ALL PRODUCTS
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
            full_cost AS "Полная себестоимость (от текущей цены)",
            logistics AS "Логистика",
            logistics_type AS "Тип логистики",
            ROUND(commission_rate * 100, 1) AS "Комиссия %",
            commission_level AS "Уровень",
            commission_key AS "Категория",
            margin AS "Маржинальность % (от текущей цены)",
            markup AS "Наценка % (от текущей цены)",
            profit AS "Прибыль (от текущей цены)",
            rec_margin AS "Маржинальность % (от рек. цены)",
            rec_profit AS "Прибыль (от рек. цены)",
            target_margin AS "Целевая маржинальность %",
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
        margin_min, margin_max = get_progress_bounds(df_products["Маржинальность % (от текущей цены)"])
        st.dataframe(
            df_products,
            use_container_width=True,
            column_config={
                "Маржинальность % (от текущей цены)": st.column_config.ProgressColumn(
                    "Маржинальность % (от текущей цены)",
                    format="%.2f%%",
                    min_value=margin_min,
                    max_value=margin_max,
                ),
                "Маржинальность % (от рек. цены)": st.column_config.NumberColumn(
                    "Маржинальность % (от рек. цены)", format="%.2f%%"
                ),
                "Наценка % (от текущей цены)": st.column_config.NumberColumn(
                    "Наценка % (от текущей цены)", format="%.2f%%"
                ),
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
