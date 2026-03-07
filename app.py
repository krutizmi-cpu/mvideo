import streamlit as st
import pandas as pd
import sqlite3
import io

st.set_page_config(page_title="M.Video Economics", layout="wide")

# ══════════════════════════════════════════════════════════════
# ЗАГРУЗКА КОМИССИЙ ИЗ CSV
# ══════════════════════════════════════════════════════════════

@st.cache_data
def load_commissions():
    df = pd.read_csv(
        "commissions.csv",
        sep=";",
        encoding="utf-8-sig",
        dtype=str
    )
    df["Комиссия"] = df["Комиссия"].str.replace(",", ".").astype(float) / 100
    df["Подкатегория"] = df["Подкатегория"].fillna("")
    df["Планнейм"] = df["Планнейм"].fillna("")
    df["Группа Товаров"] = df["Группа Товаров"].fillna("")
    return df

commission_df = load_commissions()

# ══════════════════════════════════════════════════════════════
# ФУНКЦИЯ ПОИСКА КОМИССИИ
# ══════════════════════════════════════════════════════════════

def find_commission(name: str) -> tuple:
    name_lower = name.lower()
    
    # 1️⃣ Поиск по Группе Товаров (самый точный)
    for _, row in commission_df.iterrows():
        group = str(row["Группа Товаров"]).lower()
        if group and (group in name_lower or name_lower in group):
            return row["Комиссия"], "Группа Товаров", row["Группа Товаров"]
    
    # 2️⃣ Поиск по Планнейм
    for _, row in commission_df.iterrows():
        plan = str(row["Планнейм"]).lower()
        if plan and (plan in name_lower or name_lower in plan):
            return row["Комиссия"], "Планнейм", row["Планнейм"]
    
    # 3️⃣ Поиск по Подкатегории
    for _, row in commission_df.iterrows():
        subcat = str(row["Подкатегория"]).lower()
        if subcat and subcat in name_lower:
            return row["Комиссия"], "Подкатегория", row["Подкатегория"]
    
    # 4️⃣ Дефолт
    return 0.15, "Others (дефолт)", "Others"

# ══════════════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════

def init_db():
    conn = sqlite3.connect("products.db")
    c = conn.cursor()
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
    conn.close()

init_db()

# ══════════════════════════════════════════════════════════════
# ИНТЕРФЕЙС
# ══════════════════════════════════════════════════════════════

st.title("💼 M.Video — Юнит-экономика")

tab1, tab2, tab3 = st.tabs(["➕ Добавить товар", "📋 Все товары", "📊 Аналитика"])

# ─────────────────────────────────────────────────────────────
# TAB 1: Добавить товар
# ─────────────────────────────────────────────────────────────

with tab1:
    with st.form("add_product"):
        name = st.text_input("Название товара")
        cost = st.number_input("Себестоимость (₽)", min_value=0.0, step=100.0)
        price = st.number_input("Цена продажи (₽)", min_value=0.0, step=100.0)
        stock = st.number_input("Остаток на складе (шт)", min_value=0, step=1, value=0)
        submitted = st.form_submit_button("Добавить")
        
        if submitted and name and cost > 0 and price > 0:
            rate, level, key = find_commission(name)
            
            conn = sqlite3.connect("products.db")
            c = conn.cursor()
            c.execute("""
                INSERT INTO products (name, cost, price, stock, commission_rate, commission_level, commission_key)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, cost, price, stock, rate, level, key))
            conn.commit()
            conn.close()
            
            st.success(f"✅ Товар добавлен! Комиссия {rate*100:.1f}% — найдена по уровню «{level}» → {key}")
            st.rerun()

# ─────────────────────────────────────────────────────────────
# TAB 2: Все товары
# ─────────────────────────────────────────────────────────────

with tab2:
    conn = sqlite3.connect("products.db")
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()
    
    if df.empty:
        st.info("Товаров пока нет")
    else:
        df["Комиссия М.Видео"] = (df["price"] * df["commission_rate"]).round(2)
        df["Выплата от М.Видео"] = (df["price"] - df["Комиссия М.Видео"]).round(2)
        df["Маржа"] = (df["Выплата от М.Видео"] - df["cost"]).round(2)
        df["ROI (%)"] = ((df["Маржа"] / df["cost"]) * 100).round(1)
        
        st.dataframe(df[[
            "id", "name", "cost", "price", "stock",
            "commission_rate", "commission_level", "commission_key",
            "Комиссия М.Видео", "Выплата от М.Видео", "Маржа", "ROI (%)"
        ]], use_container_width=True)
        
        # Удалить товар
        if not df.empty:
            del_id = st.number_input("ID товара для удаления", min_value=1, step=1)
            if st.button("🗑 Удалить"):
                conn = sqlite3.connect("products.db")
                c = conn.cursor()
                c.execute("DELETE FROM products WHERE id = ?", (del_id,))
                conn.commit()
                conn.close()
                st.success("Удалено")
                st.rerun()
        
        # CSV экспорт
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 Скачать CSV", csv, "mvideo_products.csv", "text/csv")

# ─────────────────────────────────────────────────────────────
# TAB 3: Аналитика
# ─────────────────────────────────────────────────────────────

with tab3:
    conn = sqlite3.connect("products.db")
    df = pd.read_sql_query("SELECT * FROM products", conn)
    conn.close()
    
    if df.empty:
        st.info("Нет данных для аналитики")
    else:
        df["Комиссия М.Видео"] = df["price"] * df["commission_rate"]
        df["Выплата от М.Видео"] = df["price"] - df["Комиссия М.Видео"]
        df["Маржа"] = df["Выплата от М.Видео"] - df["cost"]
        
        total_revenue = (df["price"] * df["stock"]).sum()
        total_commission = (df["Комиссия М.Видео"] * df["stock"]).sum()
        total_payout = (df["Выплата от М.Видео"] * df["stock"]).sum()
        total_cost = (df["cost"] * df["stock"]).sum()
        total_margin = total_payout - total_cost
        
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 Общая выручка", f"{total_revenue:,.0f} ₽")
        col2.metric("🏦 Комиссия М.Видео", f"{total_commission:,.0f} ₽")
        col3.metric("📈 Чистая маржа", f"{total_margin:,.0f} ₽")
        
        st.divider()
        
        # ТОП-5 по марже
        top5 = df.nlargest(5, "Маржа")[["name", "Маржа", "ROI (%)"]].copy()
        top5["ROI (%)"] = ((top5.index.map(lambda i: df.loc[i, "Маржа"]) / df.loc[top5.index, "cost"]) * 100).round(1)
        st.subheader("🔥 ТОП-5 по марже")
        st.dataframe(top5, use_container_width=True)
        
        # Распределение по уровню комиссии
        st.subheader("📊 Товары по уровню комиссии")
        level_counts = df["commission_level"].value_counts()
        st.bar_chart(level_counts)
