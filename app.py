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
                messages=[{"role": "system", "content": f"Determine category from: {cats_str}"},
                          {"role": "user", "content": product_name}]
            )
            ai_cat = response.choices[0].message.content.strip()
            if ai_cat in COMMISSIONS: category = ai_cat
        except: pass
            
    c.execute("INSERT OR REPLACE INTO ai_cache VALUES (?, ?)", (product_name, category))
    conn.commit()
    return category

# Title
st.markdown('<p style="font-size: 32px; font-weight: bold; color: #E31235;">📈 Расчет Юнит-Экономики М.Видео</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 10.0, 1.5)
    tax_system = st.selectbox("Налоги", ["УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", "ОСНО (20%)", "Самозанятый (4%)"])
    early_payout = st.number_input("Досрочный вывод (%)", 0.0, 10.0, 0.0)
    target_margin = st.number_input("🎯 Целевая маржа (%)", 0.0, 100.0, 20.0)
    
    st.markdown("---")
    st.subheader("📁 Массовая загрузка")
    uploaded_file = st.file_uploader("Выберите Excel файл", type=["xlsx"])

def calculate_logistics(l, w, h, weight):
    vol_weight = (l * w * h) / 5000
    billable_weight = max(weight, vol_weight)
    return 50 + (billable_weight * 20)

def find_target_price(cost, logistics, commission_rate, acq_rate, early_rate, tax_type, target_m):
    tax_rate = 0.06 if tax_type == "УСН Доходы (6%)" else 0.04 if tax_type == "Самозанятый (4%)" else 0.20
    # For Income-Expenses simplified as fixed rate on price for this formula
    m_decimal = target_m / 100
    denom = 1 - m_decimal - commission_rate - (acq_rate/100) - (early_rate/100) - tax_rate
    if denom <= 0: return 0
    return (cost + logistics) / denom

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    results = []
    
    with st.status("🔍 Анализируем товары...") as status:
        for _, row in df.iterrows():
            try:
                name, sku = str(row['наименование']), str(row['артикул'])
                price, cost = float(row['цена']), float(row['себестоимость'])
                l, w, h, weight = float(row['д']), float(row['ш']), float(row['в']), float(row['вес'])
                
                category = get_ai_category(name)
                comm_rate = COMMISSIONS.get(category, 0.10)
                logistics = calculate_logistics(l, w, h, weight)
                
                # Current metrics
                ref_fee = price * comm_rate
                acq_cost = price * (acquiring/100)
                early_cost = price * (early_payout/100)
                tax_cost = price * 0.06 if tax_system == "УСН Доходы (6%)" else 0 # Simplified
                
                profit = price - (cost + ref_fee + logistics + acq_cost + early_cost + tax_cost)
                margin = (profit / price) * 100 if price > 0 else 0
                
                # Target calculation
                rec_price = find_target_price(cost, logistics, comm_rate, acquiring, early_payout, tax_system, target_margin)
                
                results.append({
                    "Артикул": sku, "Наименование": name, "Категория": category,
                    "Тек. Цена": price, "Маржа %": round(margin, 2),
                    "Прибыль": round(profit, 2), "Целевая Маржа %": target_margin,
                    "Рек. Цена": round(rec_price, 0)
                })
            except Exception as e:
                st.error(f"Ошибка {sku}: {e}")
        status.update(label="✅ Готово!", state="complete")

    res_df = pd.DataFrame(results)
    st.subheader("📋 Результаты")
    st.dataframe(res_df.style.background_gradient(subset=['Маржа %'], cmap='RdYlGn'), use_container_width=True)
    
    csv = res_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 Скачать CSV", csv, "mvideo_analysis.csv", "text/csv")
else:
    st.info("Загрузите Excel файл.")
    st.markdown("### 📝 Пример структуры")
    st.table(pd.DataFrame([{"артикул": "SKU-1", "наименование": "Товар", "д": 10, "ш": 10, "в": 10, "вес": 0.5, "цена": 1000, "себестоимость": 500}]))
