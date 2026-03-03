import streamlit as st
import sqlite3
import pandas as pd
from openai import OpenAI

# Configuration
st.set_page_config(
    page_title="M.Видео — Юнит-экономика FBS",
    layout="wide",
    page_icon="📦"
)

DB_PATH = "products_storage.db"

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            name TEXT,
            length_cm REAL,
            width_cm REAL,
            height_cm REAL,
            weight_kg REAL,
            cost REAL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            name TEXT,
            client TEXT,
            category TEXT,
            PRIMARY KEY (name, client)
        )
    """)
    conn.commit()
    return conn

def normalize_value(raw, unit):
    try:
        v = float(str(raw).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 0.0
    u = str(unit).strip().lower()
    if u in ("мм", "mm"): return v / 10.0
    if u in ("г", "g", "гр", "gr"): return v / 1000.0
    return v

def get_ai_category(name: str, categories: list, conn, client_key: str) -> str:
    c = conn.cursor()
    row = c.execute(
        "SELECT category FROM ai_cache WHERE name=? AND client=?", 
        (name, client_key)
    ).fetchone()
    if row: return row[0]
    
    api_key = st.session_state.get("openai_key", "")
    if not api_key or not categories: return categories[0] if categories else "Неизвестно"
    
    try:
        client = OpenAI(api_key=api_key)
        cats_str = \n".join(f"- {cat}" for cat in categories)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"Ты классификатор товаров для маркетплейса {client_key}. Выбери ОДНУ категорию из списка. Ответь ТОЛЬКО её названием."},
                {"role": "user", "content": f"Товар: {name}
Категории:
{cats_str}"}
            ],
            max_tokens=60,
            temperature=0
        )
        category = resp.choices[0].message.content.strip()
        if category not in categories: category = categories[0]
    except Exception:
        category = categories[0] if categories else "Неизвестно"
        
    c.execute("INSERT OR REPLACE INTO ai_cache (name, client, category) VALUES (?,?,?)", (name, client_key, category))
    conn.commit()
    return category

def calc_tax(revenue: float, cost_total: float, regime: str):
    profit_before = revenue - cost_total
    rates = {
        "ОСНО (25% от прибыли)": ("profit", 0.25),
        "УСН Доходы (6%)": ("revenue", 0.06),
        "УСН Доходы-Расходы (15%)": ("profit", 0.15),
        "АУСН (8% от дохода)": ("revenue", 0.08),
        "УСН с НДС 5%": ("revenue", 0.05),
        "УСН с НДС 7%": ("revenue", 0.07),
    }
    mode, rate = rates.get(regime, ("profit", 0.0))
    if mode == "revenue": tax = revenue * rate
    else: tax = max(profit_before * rate, 0)
    profit_after = profit_before - tax
    margin_after = (profit_after / revenue * 100) if revenue > 0 else 0
    return round(tax, 2), round(profit_after, 2), round(margin_after, 1)

# --- M.Video Logic ---
COMMISSIONS = {
    "Автотовары": 20.5, "Аксессуары": 20.5, "Аксессуары для авто": 20.5,
    "Аксессуары для дома": 20.5, "Аксессуары для красоты": 20.5,
    "Аксессуары для кухни": 20.5, "Аксессуары для ТВ": 20.5,
    "Аксессуары для фото/видео": 20.5, "Аксессуары для электроники": 20.5,
    "Акустика": 20.5, "Аудио-видео техника": 20.5, "Бытовая химия": 20.5,
    "Гаджеты": 20.5, "Детские товары": 20.5, "Дом и сад": 20.5,
    "Инструменты": 20.5, "Канцтовары": 20.5, "Климатическая техника": 20.5,
    "Компьютерная техника": 15.5, "Компьютерные аксессуары": 15.5,
    "Красота и здоровье": 20.5, "Кухонная техника": 20.5, "Мебель": 20.5,
    "Ноутбуки и планшеты": 15.5, "Оргтехника и расходники": 15.5,
    "Освещение": 20.5, "Отдых и развлечения": 20.5, "Парфюмерия и косметика": 20.5,
    "Посуда": 20.5, "Смартфоны и связь": 15.5, "Спорт и активный отдых": 20.5,
    "Строительство и ремонт": 20.5, "ТВ и цифровое видео": 15.5,
    "Товары для взрослых": 20.5, "Товары для животных": 20.5,
    "Умный дом и безопасность": 17.5, "Фото- и видеокамеры": 15.5,
    "Цифровая техника": 15.5, "Электроника": 15.5,
}

LOGISTICS = {"S": 109, "M": 149, "L": 259, "XL": 259}

def classify_size(l, w, h, wt):
    vol = (l * w * h) / 1000.0
    if wt <= 1 and vol <= 27: return "S"
    if wt <= 5 and vol <= 54: return "M"
    if wt <= 25 and vol <= 160: return "L"
    return "XL"

# --- Main App ---
conn = init_db()

if "openai_key" not in st.session_state:
    st.session_state["openai_key"] = st.secrets.get("OPENAI_API_KEY", "")

st.header("М.Видео — Юнит-экономика (FBS)")

with st.sidebar:
    st.subheader("⚙️ Параметры расчёта")
    tax_regime = st.selectbox("Система налогообложения", [
        "ОСНО (25% от прибыли)", "УСН Доходы (6%)", "УСН Доходы-Расходы (15%)",
        "АУСН (8% от дохода)", "УСН с НДС 5%", "УСН с НДС 7%"
    ])
    st.divider()
    target_margin = st.slider("Целевая маржа, %", 0, 50, 20)
    acquiring = st.number_input("Эквайринг, %", 0.0, 5.0, 1.5)
    extra_costs = st.number_input("Доп. расходы на ед., руб", 0, 1000, 0)
    extra_logistics = st.number_input("Доп. логистика, руб", 0, 1000, 0)

# Catalog Management
with st.expander("Блок 1. Каталог товаров", expanded=True):
    col1, col2 = st.columns(2)
    with col1: dim_unit = st.selectbox("Размеры", ["см", "мм"])
    with col2: wt_unit = st.selectbox("Вес", ["кг", "г"])
    
    uploaded = st.file_uploader("Загрузить Excel (SKU, Название, Длина, Ширина, Высота, Вес, Себестоимость)", type=["xlsx"])
    if uploaded:
        df = pd.read_excel(uploaded)
        if st.button("Сохранить в базу"):
            for _, row in df.iterrows():
                try:
                    sku = str(row.get('SKU', row.get('Артикул', ''))).strip()
                    name = str(row.get('Название', row.get('Наименование', ''))).strip()
                    l = normalize_value(row.get('Длина', 0), dim_unit)
                    w = normalize_value(row.get('Ширина', 0), dim_unit)
                    h = normalize_value(row.get('Высота', 0), dim_unit)
                    wt = normalize_value(row.get('Вес', 0), wt_unit)
                    cost = float(str(row.get('Себестоимость', 0)).replace(',','.'))
                    conn.execute("INSERT OR REPLACE INTO products (sku, name, length_cm, width_cm, height_cm, weight_kg, cost) VALUES (?,?,?,?,?,?,?)",
                                 (sku, name, l, w, h, wt, cost))
                except: continue
            conn.commit()
            st.success("Каталог обновлен")

    all_p = pd.read_sql("SELECT * FROM products", conn)
    st.dataframe(all_p)

# Calculations
if not all_p.empty and st.button("Рассчитать экономику"):
    results = []
    cat_list = list(COMMISSIONS.keys())
    for _, p in all_p.iterrows():
        size = classify_size(p['length_cm'], p['width_cm'], p['height_cm'], p['weight_kg'])
        log_cost = LOGISTICS.get(size, 259) + extra_logistics
        cat = get_ai_category(p['name'], cat_list, conn, "mvideo")
        comm = COMMISSIONS.get(cat, 0)
        
        # Simple RRC calc: (Cost + Log + Extra) / (1 - Margin% - Comm% - Acq%)
        denom = 1 - (target_margin/100) - (comm/100) - (acquiring/100)
        rrc = (p['cost'] + log_cost + extra_costs) / denom if denom > 0 else 0
        
        tax, profit, marg = calc_tax(rrc, p['cost'] + log_cost + extra_costs + (rrc * (comm + acquiring)/100), tax_regime)
        
        results.append({
            "SKU": p['sku'], "Название": p['name'], "Категория": cat,
            "РРЦ": round(rrc, 2), "Прибыль": profit, "Маржа %": marg
        })
    st.dataframe(pd.DataFrame(results))
