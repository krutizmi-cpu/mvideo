import streamlit as st
import sqlite3
import pandas as pd

def init_db():
    conn = sqlite3.connect('mvideo.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
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

conn = init_db()

# Commissions data
COMMISSIONS = {
    "Автотовары": 0.10,
    "Аксессуары для авто": 0.12,
    "Аудио-Видео": 0.08,
    "Бытовая химия": 0.05,
    "Детские товары": 0.07,
    "Игрушки": 0.09,
    "Инструменты": 0.11,
    "Климатическая техника": 0.08,
    "Компьютерная техника": 0.06,
    "Красота и здоровье": 0.09,
    "Кухонная техника": 0.08,
    "Мебель": 0.12,
    "Освещение": 0.10,
    "Офисная техника": 0.07,
    "Планшеты": 0.05,
    "Посуда": 0.10,
    "Продукты питания": 0.05,
    "Сад и огород": 0.11,
    "Сантехника": 0.10,
    "Смартфоны": 0.04,
    "Спорт и отдых": 0.09,
    "Строительство и ремонт": 0.11,
    "ТВ и цифровое видео": 0.07,
    "Текстиль": 0.10,
    "Товары для дома": 0.09,
    "Товары для животных": 0.07,
    "Умный дом": 0.08,
    "Фото и видео": 0.07,
    "Хобби и творчество": 0.09,
    "Цифровое фото и видео": 0.07,
    "Электроника": 0.08,
    "Электросамокаты": 0.08,
    "Apple": 0.03,
    "Gaming": 0.09,
    "Laptops": 0.06,
    "PC Components": 0.07,
    "Peripherals": 0.10,
    "Stationery": 0.12,
    "Others": 0.10
}

st.title("M.Video Unit Economics Calculator")

with st.sidebar:
    st.header("Ввод данных")
    name = st.text_input("Название товара", "Товар")
    price = st.number_input("Цена продажи (руб)", min_value=0.0, value=1000.0)
    cost = st.number_input("Себестоимость (руб)", min_value=0.0, value=500.0)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        length = st.number_input("Д (см)", min_value=0.0, value=10.0)
    with col2:
        width = st.number_input("Ш (см)", min_value=0.0, value=10.0)
    with col3:
        height = st.number_input("В (см)", min_value=0.0, value=10.0)
    
    weight = st.number_input("Вес (кг)", min_value=0.0, value=0.5)
    
    category = st.selectbox("Категория", list(COMMISSIONS.keys()))

# Расчеты
referral_fee = price * COMMISSIONS.get(category, 0.10)

# Логистика
volumetric_weight = (length * width * height) / 5000
shipping_weight = max(weight, volumetric_weight)
logistics_cost = 50 + (shipping_weight * 20)

tax = price * 0.06
total_expenses = referral_fee + logistics_cost + tax + cost
profit = price - total_expenses
margin = (profit / price) * 100 if price > 0 else 0

# Отображение результатов
st.header(f"Результаты для: {name}")
c1, c2, c3 = st.columns(3)
c1.metric("Прибыль", f"{profit:.2f} руб")
c2.metric("Маржа", f"{margin:.2f}%")
c3.metric("Расходы", f"{total_expenses:.2f} руб")

st.subheader("Детализация расходов")
breakdown = {
    "Статья": ["Цена продажи", "Себестоимость", "Комиссия", "Логистика", "Налог", "Итого расходов"],
    "Значение (руб)": [price, cost, referral_fee, logistics_cost, tax, total_expenses]
}
st.table(pd.DataFrame(breakdown))

if st.button("Сохранить в историю"):
    c = conn.cursor()
    c.execute("INSERT INTO products (name, length_cm, width_cm, height_cm, weight_kg, cost) VALUES (?, ?, ?, ?, ?, ?)", (name, length, width, height, weight, cost))
    conn.commit()
    st.success("Сохранено!")

st.subheader("Последние расчеты")
history = pd.read_sql("SELECT * FROM products ORDER BY rowid DESC LIMIT 5", conn)
st.dataframe(history)
