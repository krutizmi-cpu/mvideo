import streamlit as st
import sqlite3
import pandas as pd
import io
from openai import OpenAI

# Page config
st.set_page_config(page_title="M.Video Economics", layout="wide")

# Database initialization
@st.cache_resource
def init_db():
    conn = sqlite3.connect("mvideo.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS ai_cache (name TEXT PRIMARY KEY, category TEXT)")
    conn.commit()
    return conn

conn = init_db()

# Commissions data (Updated based on 2025 PDF)
COMMISSIONS = {
    "Смартфоны и связь": 0.07,
    "Смартфоны": 0.07,
    "Ноутбуки": 0.07,
    "Планшеты": 0.07,
    "Компьютеры и комплектующие": 0.08,
    "Телевизоры": 0.09,
    "Аудиотехника": 0.10,
    "Аудио-Видео": 0.10,
    "Фото и видеотехника": 0.11,
    "Крупная бытовая техника": 0.13,
    "Бытовая техника": 0.14,
    "Мелкая бытовая техника": 0.195,
    "Мебель": 0.17,
    "Посуда": 0.20,
    "Товары для кухни": 0.18,
    "Текстиль для дома": 0.19,
    "Товары для ванной": 0.18,
    "Книги": 0.24,
    "Канцелярские товары": 0.22,
    "Одежда": 0.20,
    "Обувь": 0.21,
    "Аксессуары": 0.19,
    "Красота и здоровье": 0.20,
    "Автотовары": 0.205,
    "Others": 0.15,
}

def get_ai_category(product_name, api_key=None):
    c = conn.cursor()
    c.execute("SELECT category FROM ai_cache WHERE name=?", (product_name,))
    cached = c.fetchone()
    if cached:
        return cached[0]

    category = "Others"
    name_lower = str(product_name).lower()

    for cat in COMMISSIONS.keys():
        if cat.lower() in name_lower:
            category = cat
            break

    if api_key and category == "Others":
        try:
            client = OpenAI(api_key=api_key)
            prompt = (
                f"Определи категорию товара '{product_name}' из списка: "
                f"{', '.join(COMMISSIONS.keys())}. Ответь только названием категории."
            )
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                timeout=5,
            )
            ai_cat = response.choices[0].message.content.strip()
            if ai_cat in COMMISSIONS:
                category = ai_cat
        except Exception:
            pass

    c.execute("INSERT OR REPLACE INTO ai_cache VALUES (?, ?)", (product_name, category))
    conn.commit()
    return category

st.markdown(
    '<p style="font-size: 32px; font-weight: bold; color: #E31235;">📈 Расчет Юнит-Экономики М.Видео</p>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("⚙️ Глобальные настройки")
    acquiring = st.number_input("Эквайринг (%)", 0.0, 10.0, 1.5)
    tax_system = st.selectbox("Налоги", ["УСН Доходы (6%)", "УСН Доходы-Расходы (15%)", "ОСНО (20%)", "Самозанятый (4%)"])
    early_payout = st.number_input("Досрочный вывод (%)", 0.0, 10.0, 0.0)
    target_margin = st.number_input("🎯 Целевая маржа (%)", 0.0, 100.0, 20.0)

    st.markdown("---")
    openai_key = st.text_input("OpenAI API Key (опционально)", type="password")

    st.markdown("---")
    st.subheader("📁 Массовая загрузка")

    template_df = pd.DataFrame(columns=["артикул", "наименование", "д", "ш", "в", "вес", "цена", "себестоимость"])
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
    uploaded_file = st.file_uploader("Загрузите файл", type=["xlsx"])

def calculate_logistics(l, w, h, weight):
    vol_weight = (l * w * h) / 5000
    billable_weight = max(weight, vol_weight)
    return 50 + (billable_weight * 20)

def find_target_price(cost, logistics, commission_rate, acq_rate, early_rate, tax_type, target_m):
    tax_rate = 0.06 if tax_type == "УСН Доходы (6%)" else 0.04 if tax_type == "Самозанятый (4%)" else 0.20
    m_decimal = target_m / 100
    denom = 1 - m_decimal - commission_rate - (acq_rate / 100) - (early_rate / 100) - tax_rate
    if denom <= 0:
        return 0
    return (cost + logistics) / denom

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df.columns = [str(c).strip().lower() for c in df.columns]
    results = []

    with st.status("🔍 Обработка...") as status:
        for index, row in df.iterrows():
            try:
                name = str(row.get("наименование", "Неизвестно"))
                sku = str(row.get("артикул", f"Row-{index}"))
                price = float(row.get("цена", 0))
                cost = float(row.get("себестоимость", 0))
                l = float(row.get("д", 0))
                w = float(row.get("ш", 0))
                h = float(row.get("в", 0))
                weight = float(row.get("вес", 0))

                category = get_ai_category(name, openai_key)
                comm_rate = COMMISSIONS.get(category, 0.15)
                logistics = calculate_logistics(l, w, h, weight)

                ref_fee = price * comm_rate
                acq_cost = price * (acquiring / 100)
                early_cost = price * (early_payout / 100)
                tax_cost = price * 0.06 if tax_system == "УСН Доходы (6%)" else 0

                profit = price - (cost + ref_fee + logistics + acq_cost + early_cost + tax_cost)
                margin_pct = (profit / price) * 100 if price > 0 else 0.0

                rec_price = find_target_price(cost, logistics, comm_rate, acquiring, early_payout, tax_system, target_margin)

                results.append(
                    {
                        "Артикул": sku,
                        "Наименование": name,
                        "Категория": category,
                        "Тек. Цена": price,
                        "Маржа %": round(margin_pct, 2),
                        "Маржа": (margin_pct / 100.0),
                        "Прибыль": round(profit, 2),
                        "Цель Маржа %": target_margin,
                        "Рек. Цена": round(rec_price, 0),
                    }
                )
            except Exception as e:
                st.error(f"Ошибка: {e}")
        status.update(label="✅ Готово!", state="complete")

    if results:
        res_df = pd.DataFrame(results)

        st.dataframe(
            res_df,
            use_container_width=True,
            column_config={
                "Маржа": st.column_config.NumberColumn("Маржа", format="%.2f%%"),
                "Маржа %": st.column_config.NumberColumn("Маржа %", format="%.2f"),
                "Тек. Цена": st.column_config.NumberColumn("Тек. Цена", format="%.2f"),
                "Прибыль": st.column_config.NumberColumn("Прибыль", format="%.2f"),
                "Рек. Цена": st.column_config.NumberColumn("Рек. Цена", format="%.0f"),
            },
        )

        csv = res_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 Скачать результат", csv, "results.csv", "text/csv")
    else:
        st.warning("Нет данных для отображения.")
else:
    st.info("Загрузите файл Excel для начала расчета.")
    template_df = pd.DataFrame(columns=["артикул", "наименование", "д", "ш", "в", "вес", "цена", "себестоимость"])
    template_df.loc[0] = ["SKU-001", "Пример товара", 10, 10, 10, 0.5, 2990, 1500]
    st.table(template_df)
