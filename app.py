import streamlit as st
import sqlite3
import pandas as pd
import json
import os
from openai import OpenAI

# Page config
st.set_page_config(page_title="M.Video Economics", layout="wide")

# Database initialization
def init_db():
    conn = sqlite3.connect('mvideo.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT,
            name TEXT,
            length_cm REAL,
            width_cm REAL,
            height_cm REAL,
            weight_kg REAL,
            cost REAL,
            price REAL,
            category TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            name TEXT PRIMARY KEY,
            category TEXT
        )
    """)
    conn.commit()
    return conn

conn = init_db()

# Commissions data
COMMISSIONS = {
    "Автотовары": 0.10, "Аксессуары для авто": 0.12, "Аудио-Видео": 0.08, "Бытовая химия": 0.05,
    "Детские товары": 0.07, "Игрушки": 0.09, "Инструменты": 0.11, "Климатическая техника": 0.08,
    "Компьютерная техника": 0.06, "Красота и здоровье": 0.09, "Кухонная техника": 0.08, "Мебель": 0.12,
    "Освещение": 0.10, "Офисная техника": 0.07, "Планшеты": 0.05, "Посуда": 0.10, "Продукты питания": 0.05,
    "Сад и огород": 0.11, "Сантехника": 0.10, "Смартфоны": 0.04, "Спорт и отдых": 0.09,
    "Строительство и ремонт": 0.11, "ТВ и цифровое видео": 0.07, "Текстиль": 0.10, "Товары для дома": 0.09,
    "Товары для животных": 0.07, "Умный дом": 0.08, "Фото и видео": 0.07, "Хобби и творчество": 0.09,
    "Цифровое фото и видео": 0.07, "Электроника": 0.08, "Электросамокаты": 0.08, "Apple": 0.03,
    "Gaming": 0.09, "Laptops": 0.06, "PC Components": 0.07, "Peripherals": 0.10, "Stationery": 0.12, "Others": 0.10
}

def get_ai_category(product_name):
    c = conn.cursor()
    c.execute("SELECT category FROM ai_cache WHERE name=?", (product_name,))
    cached = c.fetchone()
    if cached: return cached[0]
    
    category = "Others"
    name_lower = product_name.lower()
    for cat in COMMISSIONS.keys():
        if cat.lower() in name_lower:
            category = cat
            break
            
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            client = OpenAI(api_key=api_key)
            cats_str = ", ".join(COMMISSIONS.keys())
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": f"Determine product category from: {cats_str}"},
                          {"role": "user", "content": product_name}]
            )
            ai_cat = response.choices[0].message.content.strip()
            if ai_cat in COMMISSIONS: category = ai_cat
        except: pass
            
    c.execute("INSERT OR REPLACE INTO ai_cache VALUES (?, ?)", (product_name, category))
    conn.commit()
    return category

# Custom CSS for UI
st.markdown("""
    <style>
    .main-title { font-size: 32px; font-weight: bold; color: #E31235; margin-bottom: 20px; }
    .stTable { border: 1px solid #f0f2f6; border-radius: 10px; }
    .info-text { color: #555; font-size: 14px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-title">📈 Расчет Юнит-Экономики М.Видео</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 10.0, 1.5, help="Процент комиссии банка за эквайринг")
    tax_system = st.selectbox("Система налогообложения", ["УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", "ОСНО (20%)", "Самозанятый (4%)"])
    early_payout = st.number_input("Досрочный вывод (%)", 0.0, 10.0, 0.0, help="Комиссия за ускоренные выплаты")
    
    st.markdown("---")
    st.subheader("📁 Массовая загрузка")
    uploaded_file = st.file_uploader("Выберите Excel файл", type=["xlsx"])

def calculate_logistics(l, w, h, weight):
    vol_weight = (l * w * h) / 5000
    billable_weight = max(weight, vol_weight)
    return 50 + (billable_weight * 20)

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    results = []
    
    with st.status("🔍 Анализируем товары...", expanded=True) as status:
        for _, row in df.iterrows():
            try:
                name = str(row['наименование'])
                sku = str(row['артикул'])
                price = float(row['цена'])
                cost = float(row['себестоимость'])
                l, w, h = float(row['д']), float(row['ш']), float(row['в'])
                weight = float(row['вес'])
                
                category = get_ai_category(name)
                commission_rate = COMMISSIONS.get(category, 0.10)
                
                ref_fee = price * commission_rate
                acq_cost = price * (acquiring / 100)
                early_payout_cost = price * (early_payout / 100)
                logistics = calculate_logistics(l, w, h, weight)
                
                if tax_system == "УСН Доходы (6%)": tax_cost = price * 0.06
                elif tax_system == "УСН Доходы-Расходы (15%)": tax_cost = max(0, price - cost - ref_fee - logistics) * 0.15
                elif tax_system == "ОСНО (20%)": tax_cost = price * 0.20
                else: tax_cost = price * 0.04
                
                total_exp = cost + ref_fee + logistics + acq_cost + early_payout_cost + tax_cost
                profit = price - total_exp
                margin = (profit / price) * 100 if price > 0 else 0
                
                results.append({
                    "Артикул": sku, "Наименование": name, "Категория": category,
                    "Цена": price, "Себес": cost, "Логистика": round(logistics, 2), 
                    "Комиссия": round(ref_fee, 2), "Налог": round(tax_cost, 2), 
                    "Прибыль": round(profit, 2), "Маржа %": round(margin, 2)
                })
            except Exception as e:
                st.error(f"Ошибка в строке {sku}: {e}")
        status.update(label="✅ Расчет завершен!", state="complete", expanded=False)

    res_df = pd.DataFrame(results)
    
    st.subheader("📋 Результаты расчета")
    st.dataframe(res_df.style.background_gradient(subset=['Маржа %'], cmap='RdYlGn'), use_container_width=True)
    
    c1, c2 = st.columns([1, 4])
    with c1:
        csv = res_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Скачать CSV", csv, "unit_economics.csv", "text/csv", use_container_width=True)
else:
    st.info("👋 Добро пожаловать! Чтобы начать, загрузите Excel файл с товарами.")
    
    st.markdown("### 📝 Структура Excel файла")
    st.markdown("""
    | Артикул | Наименование | Д | Ш | В | Вес | Цена | Себестоимость |
    | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
    | SKU-123 | Чайник электрический | 20 | 20 | 30 | 1.5 | 2990 | 1500 |
    """)
    st.caption("💡 *Наименование используется для автоматического определения категории с помощью ИИ.*")
