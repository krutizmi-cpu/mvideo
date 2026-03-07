import streamlit as st
import sqlite3
import pandas as pd
import io
import json
from openai import OpenAI

# ══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="M.Video Economics", layout="wide")

# ══════════════════════════════════════════════════════════════
# ЗАГРУЗКА КОМИССИЙ ИЗ CSV
# ══════════════════════════════════════════════════════════════
@st.cache_data
def load_commissions():
    try:
        df = pd.read_csv(
            "https://raw.githubusercontent.com/krutizmi-cpu/mvideo/main/commissions.csv",
            sep=";",
            encoding="utf-8-sig",
            dtype=str
        )
        df["Комиссия"] = df["Комиссия"].str.replace(",", ".").astype(float) / 100
        for col in ["Подкатегория", "Планнейм", "Группа Товаров"]:
            df[col] = df[col].fillna("").str.strip()
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки комиссий: {e}")
        return pd.DataFrame(columns=["Подкатегория", "Планнейм", "Группа Товаров", "Комиссия"])

DEFAULT_COMMISSION_RATE = 0.20

commission_df = load_commissions()

# Оптимизация поиска: переводим в список словарей один раз
commissions_list = commission_df.to_dict('records')

def find_commission(name: str, openai_key: str = None) -> tuple:
    if not name or name == "Неизвестно":
        return DEFAULT_COMMISSION_RATE, "Others (дефолт)", "Others"
    
    name_lower = name.lower()
    
    # 1. Сначала ищем по Группе Товаров (самый точный уровень)
    for row in commissions_list:
        group = row["Группа Товаров"].lower()
        if group and (group in name_lower or name_lower in group):
            return row["Комиссия"], "Группа Товаров", row["Группа Товаров"]
            
    # 2. Затем по Планнейму
    for row in commissions_list:
        plan = row["Планнейм"].lower()
        if plan and (plan in name_lower or name_lower in plan):
            return row["Комиссия"], "Планнейм", row["Планнейм"]
            
    # 3. Затем по Подкатегории
    for row in commissions_list:
        subcat = row["Подкатегория"].lower()
        if subcat and subcat in name_lower:
            return row["Комиссия"], "Подкатегория", row["Подкатегория"]

    # 4. Если есть API ключ и ничего не ншли — пробуем AI
    if openai_key:
        # Проверяем кэш AI
        c = conn.cursor()
        c.execute("SELECT category FROM ai_cache WHERE name = ?", (name,))
        cached = c.fetchone()
        if cached:
            # Находим данные по кэшированной категории
            cat_name = cached[0]
            for row in commissions_list:
                if row["Группа Товаров"] == cat_name or row["Планнейм"] == cat_name or row["Подкатегория"] == cat_name:
                    return row["Комиссия"], "AI Match", cat_name
        
        # Если в кэше нет — зовем AI (очень упрощенно для примера)
        # В реальном приложении здесь должен быть запрос к OpenAI
        # Но чтобы не вешать приложение, оставим заглушку или сделаем быстрый запрос
    
    return DEFAULT_COMMISSION_RATE, "Others (дефолт)", "Others"

# ══════════════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════
@st.cache_resource
def init_db():
    conn = sqlite3.connect("mvideo.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            name TEXT PRIMARY KEY,
            category TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cost REAL NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            commission_rate REAL NOT NULL,
            commission_level TEXT NOT NULL,
            commission_key TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

conn = init_db()

# ══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════
def calculate_logistics(l, w, h, weight):
    vol_weight = (l * w * h) / 5000
    billable_weight = max(weight, vol_weight)
    return 50 + (billable_weight * 20)

def calculate_tax(price, cost, logistics, commission, acq, early, tax_system):
    if tax_system == "УСН Доходы (6%)":
        return price * 0.06
    elif tax_system == "Самозанятый (4%)":
        return price * 0.04
    elif tax_system == "ОСНО (20%)":
        return price * 0.20
    elif tax_system == "УСН Доходы-Расходы (15%)":
        # Налог 15% от (Доходы - Расходы)
        expenses = cost + logistics + commission + acq + early
        profit_before_tax = price - expenses
        return max(0, profit_before_tax * 0.15)
    else:
        return 0

def find_target_price(cost, logistics, commission_rate, acq_rate, early_rate, tax_type, target_m):
    # Приблизительный расчет целевой цены
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
        # Упрощенно для этой системы (налог на прибыль)
        # Price = Cost + Log + Comm + Acq + Early + TargetProfit + 0.15*(Price - ...)
        # Denom adjusted for 15% on margin
        denom = (1 - m_decimal - commission_rate - acq_dec - early_dec) * 0.85
        if denom <= 0: return 0
        return (cost + logistics) / denom
        
    denom = 1 - m_decimal - commission_rate - acq_dec - early_dec - tax_rate
    if denom <= 0:
        return 0
    return (cost + logistics) / denom


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

# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 10.0, 1.5)
    tax_system = st.selectbox(
        "Налоги",
        ["УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", "ОСНО (20%)", "Самозанятый (4%)"]
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
        use_container_width=True
    )
    uploaded_file = st.file_uploader("Загрузите файл Excel", type=["xlsx"])

# ══════════════════════════════════════════════════════════════
# ЗАГОЛОВОК + ТАБЫ
# ══════════════════════════════════════════════════════════════
st.title("💼 M.Video — Юнит-экономика")
tab1, tab2, tab3, tab4 = st.tabs([
    "📦 Массовый расчёт (Excel)",
    "➕ Добавить товар",
    "📋 Все товары",
    "📊 Аналтика"
])

# ══════════════════════════════════════════════════════════════
# TAB 1: Массовый расчёт из Excel
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
                    sku = str(row.get("артикул", f"Row-{index}"))
                    price = float(row.get("цена", 0))
                    cost = float(row.get("себестоимость", 0))
                    l = float(row.get("д", 0))
                    w = float(row.get("ш", 0))
                    h = float(row.get("в", 0))
                    weight = float(row.get("вес", 0))
                    
                    comm_rate, comm_level, comm_key = find_commission(name, openai_key)
                    logistics = calculate_logistics(l, w, h, weight)
                    ref_fee = price * comm_rate
                    acq_cost = price * (acquiring / 100)
                    early_cost = price * (early_payout / 100)
                    tax_cost = calculate_tax(price, cost, logistics, ref_fee, acq_cost, early_cost, tax_system)
                    
                    profit = price - (cost + ref_fee + logistics + acq_cost + early_cost + tax_cost)
                    margin = (profit / price) * 100 if price > 0 else 0
                    rec_price = find_target_price(
                        cost, logistics, comm_rate,
                        acquiring, early_payout,
                        tax_system, target_margin
                    )
                    
                    results.append({
                        "Артикул": sku,
                        "Наименование": name,
                        "Категория": comm_key,
                        "Уровень": comm_level,
                        "Комиссия %": round(comm_rate * 100, 1),
                        "Тек. Цена": price,
                        "Логистика": round(logistics, 2),
                        "Маржа %": round(margin, 2),
                        "Прибыль": round(profit, 2),
                        "Цель Маржа %": target_margin,
                        "Рек. Цена": round(rec_price, 0)
                    })
                except Exception as e:
                    st.error(f"Ошибка в строке {index}: {e}")
            status.update(label="✅ Готово!", state="complete")
        
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
                }
            )
            csv = res_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 Скачать результат", csv, "results.csv", "text/csv")
        else:
            st.warning("Нет данных для отображения.")
    else:
        st.info("Загрузите файл Excel через боковую панель для начала расчёта.")
        st.table(template_df)

# ══════════════════════════════════════════════════════════════
# TAB 2: Добавить товар вручную
# ══════════════════════════════════════════════════════════════
with tab2:
    with st.form("add_product"):
        name_input = st.text_input("Название товара")
        cost_input = st.number_input("Себестоимость (₽)", min_value=0.0, step=100.0)
        price_input = st.number_input("Цена продажи (₽)", min_value=0.0, step=100.0)
        stock_input = st.number_input("Остаток на складе (шт)", min_value=0, step=1, value=0)
        submitted = st.form_submit_button("Добавить")
        
        if submitted and name_input and cost_input > 0 and price_input > 0:
            rate, level, key = find_commission(name_input, openai_key)
            c = conn.cursor()
            c.execute("""
                INSERT INTO products 
                (name, cost, price, stock, commission_rate, commission_level, commission_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name_input, cost_input, price_input, stock_input, rate, level, key))
            conn.commit()
            st.success(
                f"✅ Товар добавлен! Комиссия {rate*100:.1f}% — "
                f"найдена по уровню «{level}» → {key}"
            )
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 3: Все товары
# ══════════════════════════════════════════════════════════════
with tab3:
    df_products = pd.read_sql_query("SELECT * FROM products", conn)
    if df_products.empty:
        st.info("Товаров пока нет")
    else:
        df_products["Комиссия М.Видео"] = (df_products["price"] * df_products["commission_rate"]).round(2)
        df_products["Выплата от М.Видео"] = (df_products["price"] - df_products["Комиссия М.Видео"]).round(2)
        df_products["Маржа"] = (df_products["Выплата от М.Видео"] - df_products["cost"]).round(2)
        df_products["ROI (%)"] = ((df_products["Маржа"] / df_products["cost"]) * 100).round(1)
        
        margin_min, margin_max = get_progress_bounds(df_products["Маржа"])
        roi_min, roi_max = get_progress_bounds(df_products["ROI (%)"])
        
        st.dataframe(
            df_products[[
                "id", "name", "cost", "price", "stock", 
                "commission_rate", "commission_level", "commission_key",
                "Комиссия М.Видео", "Выплата от М.Видео", "Маржа", "ROI (%)"
            ]],
            use_container_width=True,
            column_config={
                "Маржа": st.column_config.ProgressColumn(
                    "Маржа (₽)",
                    format="%.2f ₽",
                    min_value=margin_min,
                    max_value=margin_max,
                ),
                "ROI (%)": st.column_config.ProgressColumn(
                    "ROI (%)",
                    format="%.1f%%",
                    min_value=roi_min,
                    max_value=roi_max,
                )
            }
        )
        
        st.markdown("---")
        del_id = st.number_input("ID товара для удаления", min_value=0, step=1, value=0)
        if st.button("🗑️ Удалить товар") and del_id > 0:
            c = conn.cursor()
            c.execute("DELETE FROM products WHERE id = ?", (del_id,))
            conn.commit()
            st.success(f"Товар с ID {del_id} удалён.")
            st.rerun()

# ══════════════════════════════════════════════════════════════
# TAB 4: Аналитика
# ══════════════════════════════════════════════════════════════
with tab4:
    df_analytics = pd.read_sql_query("SELECT * FROM products", conn)
    if df_analytics.empty:
        st.info("Нет данных для аналитики. Добавьте товары.")
    else:
        df_analytics["Комиссия М.Видео"] = (df_analytics["price"] * df_analytics["commission_rate"]).round(2)
        df_analytics["Выплата от М.Видео"] = (df_analytics["price"] - df_analytics["Комиссия М.Видео"]).round(2)
        df_analytics["Маржа"] = (df_analytics["Выплата от М.Видео"] - df_analytics["cost"]).round(2)
        df_analytics["ROI (%)"] = ((df_analytics["Маржа"] / df_analytics["cost"]) * 100).round(1)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Товаров", len(df_analytics))
        col2.metric("Сред. маржа (%)", f"{(df_analytics['Маржа'] / df_analytics['price'] * 100).mean():.1f}%")
        col3.metric("Сред. ROI (%)", f"{df_analytics['ROI (%)'].mean():.1f}%")
        col4.metric("Общая прибыль (₽)", f"{(df_analytics['Маржа'] * df_analytics['stock']).sum():,.0f} ₽")
        
        st.markdown("---")
        st.subheader("📊 Маржа по товарам")
        st.bar_chart(df_analytics.set_index("name")["Маржа"])
        
        st.subheader("📈 ROI по товарам")
        st.bar_chart(df_analytics.set_index("name")["ROI (%)"])
