import streamlit as st
import sqlite3
import pandas as pd
import io
from openai import OpenAI

st.set_page_config(page_title="M.Video Economics", layout="wide")

# ──────────────────────────────────────────────────────────────
# КОМИССИИ (из тарифного файла 2025, 3 листа, 894 строки)
# Уровни поиска: Группа Товаров → Планнейм → Подкатегория → Others
# ──────────────────────────────────────────────────────────────

COMMISSIONS_BY_GROUP = {
    "Аварийный наб авт": 0.205, "Автомобильная аптечка": 0.205, "Домкрат": 0.205,
    "Дорожный знак": 0.205, "Жгут для ремонта шин": 0.205, "Жилет светоотражающий": 0.205,
    "Знак аварийной остановки": 0.205, "Клей для ремонта шин": 0.205, "Лопата автомобильная": 0.205,
    "Накладка для домкрата": 0.205, "Наклейка на авто": 0.205, "Страховочная опора": 0.205,
    "Табличка для авто": 0.205, "Трос буксировочный": 0.205, "Упор противооткатный": 0.205,
    "Автомобильный манометр": 0.205, "Ареометр": 0.205, "Глубиномер протектора шин": 0.205,
    "Инструмент для кручения болта": 0.205, "Инструмент для чистки клемм": 0.205,
    "Инструмент запрессовочно-выпресс": 0.205, "Ключ баллонный": 0.205,
    "Ключ динамометрический": 0.205, "Ключ свечной": 0.205,
    "Комплектующие для лебедки": 0.205, "Компрессометр": 0.205,
    "Набор автомобильных инструменто": 0.205, "Набор для ремонта кабеля": 0.205,
    "Набор для ремонта камер": 0.205, "Съемник": 0.205, "Тестер аккумулятора": 0.205,
    "Тестер электрики": 0.205, "Удлинитель для домкрата": 0.205,
    "Шиномонтажный инструмент": 0.205, "Шуруповерт для авто": 0.205,
    "Набор ключей автомобильных": 0.205, "Ящик для инструментов авто": 0.205,
    "Адаптер": 0.205, "Держатель для номерного знака": 0.205,
    # Товары для школы
    "Блокнот для флипчартов": 0.235, "Блокнот творческий": 0.235, "Бумага для заметок": 0.235,
    "Бумага для оргтехники": 0.235, "Бумага миллиметровочная": 0.235, "Гостевая книга": 0.235,
    "Грамота и диплом": 0.235, "Обложка для документов": 0.235, "Анатомическая модель": 0.235,
    "Банковская резинка": 0.235, "Бейдж": 0.235, "Бизнес-набор": 0.235,
    "Блок": 0.235, "Браслет контрольный": 0.235, "Глобус": 0.235,
    "Грифель": 0.235, "Губка для досок": 0.235, "Демосистема": 0.235,
    "Держатель канцелярский": 0.235, "Диспенсер канцелярский": 0.235,
    "Доска для записей": 0.235, "Дырокол": 0.235,
    "Жидкость для снятия этикетки": 0.235, "Зажим канцелярский": 0.235, "Закладка": 0.235,
    "Закладка магнитная": 0.235, "Информационная стойка": 0.235, "Калькулятор": 0.235,
    "Канцелярский набор": 0.235, "Клей-карандаш": 0.235, "Клейкая лента": 0.235,
    "Клейкая лента декоративная": 0.235, "Клейкие листки": 0.235, "Ластик": 0.235,
    "Линейка": 0.235, "Маркер для доски": 0.235, "Маркер перманентный": 0.235,
    "Маркер текстовый": 0.235, "Ножницы": 0.235, "Ножницы фигурные": 0.235,
    "Нож канцелярский": 0.235, "Нож скрапбукинг": 0.235, "Папка": 0.235,
    "Папка-конверт": 0.235, "Подставка канцелярская": 0.235, "Разделитель страниц": 0.235,
    "Ручка гелевая": 0.235, "Ручка капиллярная": 0.235, "Ручка перьевая": 0.235,
    "Ручка роллер": 0.235, "Ручка шариковая": 0.235, "Скоба для степлера": 0.235,
    "Скотч двусторонний": 0.235, "Степлер": 0.235, "Точилка": 0.235,
    "Чехол для ручки": 0.235, "Короб почтовый": 0.235, "Пакет почтовый": 0.235,
    "Почтовая марка": 0.235, "Печать для пломбирования": 0.235, "Пломба": 0.235,
    "Пломба-наклейка": 0.235, "Пломбиратор": 0.235, "Пломбировочная лента": 0.235,
    "Проволока пломбировочная": 0.235, "Сургуч": 0.235,
    "Мешок для обуви школьный": 0.235, "Пенал": 0.235, "Рюкзак школьный": 0.235,
    "Рюкзак школьный с экраном": 0.235, "Бумага для черчения": 0.235,
    "Готовальня": 0.235, "Линейка для черчения": 0.235, "Рапидограф": 0.235,
    "Тубус": 0.235, "Тушь для рапидографа": 0.235, "Циркуль": 0.235,
    "Чернила": 0.235, "Чертежная доска": 0.235,
    # Транспортные средства
    "Автомобиль бензиновый": 0.005, "Автомобиль гибридный": 0.005,
    "Автомобиль дизельный": 0.005, "Автомобиль электрический": 0.005,
    "Багги": 0.005, "Велосипед взрослый": 0.005, "Велосипед детский": 0.005,
    "Гироскутер": 0.005, "Квадроцикл": 0.005, "Мопед": 0.005, "Мотоцикл": 0.005,
    "Мотоцикл электрический": 0.005, "Самокат": 0.005, "Электровелосипед": 0.005,
    "Электросамокат": 0.005, "Скутер": 0.005,
}

COMMISSIONS_BY_PLAN = {
    "DJ оборудование и аксессуары": 0.155,
    "Аварийные принадлежности": 0.205,
    "Автомобиль новый": 0.005,
    "Автомобильные инструменты": 0.205,
    "Акс/комплектующие к фото,видеок": 0.155,
    "Аксессуары для аудиотехники": 0.155,
    "Аксессуары для видеотехники": 0.155,
    "Аксессуары для компьютеров": 0.215,
    "Аксессуары для микрокомпьютеров": 0.215,
    "Аксессуары для наушников": 0.155,
    "Аксессуары для ноутбуков": 0.215,
    "Аксессуары для планшетов": 0.215,
    "Аксессуары для смартфонов и телеф": 0.215,
    "Аксессуары для телевизоров, ТВ пр": 0.155,
    "Аксессуары для умных гаджетов": 0.215,
    "Аксессуары для электронных книг": 0.215,
    "Аксессуары/комплектующие для ор": 0.215,
    "Антенны и аксессуары": 0.155,
    "Аудиотехника и колонки": 0.155,
    "Багги": 0.005,
    "Бумажная продукция": 0.235,
    "Велосипеды": 0.005,
    "Видеонаблюдение": 0.155,
    "Видеотехника": 0.155,
    "Гироскутер": 0.005,
    "Графические планшеты и стилусы": 0.215,
    "Жёсткие диски и флеш-носители": 0.215,
    "Зарядные устройства и АКБ для авт": 0.205,
    "Зарядные устройства и кабели": 0.215,
    "Игровые манипуляторы и аксессуары": 0.215,
    "Игровые приставки": 0.07,
    "Источники бесперебойного питания": 0.155,
    "Кабели и адаптеры": 0.155,
    "Канцелярские принадлежности": 0.235,
    "Квадроциклы": 0.005,
    "Климатическое оборудование": 0.155,
    "Компьютерная периферия": 0.215,
    "Компьютеры и серверы": 0.215,
    "Мелкая бытовая техника": 0.155,
    "Мобильные телефоны": 0.07,
    "Мониторы": 0.215,
    "Мотоциклы": 0.005,
    "Наушники и гарнитуры": 0.155,
    "Нетбуки, ноутбуки, ультрабуки": 0.07,
    "Носители для записи": 0.155,
    "Оперативная память и кэш": 0.215,
    "Оптика и бинокли": 0.155,
    "Оргтехника": 0.215,
    "Освещение": 0.155,
    "Планшеты": 0.07,
    "Письменные принадлежности": 0.235,
    "Почтовые принадлежности": 0.235,
    "Принадлежности для пломбировки": 0.235,
    "Проекторы и экраны": 0.155,
    "Расходные материалы для оргтехник": 0.215,
    "Роутеры и сетевое оборудование": 0.215,
    "Рюкзаки, мешки, пеналы и аксессуа": 0.235,
    "Самокаты": 0.005,
    "Сетевые фильтры и удлинители": 0.155,
    "Смарт-часы и браслеты": 0.215,
    "Смартфоны": 0.07,
    "Системы умного дома": 0.215,
    "Телевизоры": 0.13,
    "Торговое оборудование": 0.215,
    "Тюнеры и ресиверы": 0.155,
    "Умные гаджеты": 0.215,
    "Фотоаппараты и аксессуары": 0.155,
    "Чертежные принадлежности": 0.235,
    "Электровелосипеды": 0.005,
    "Электросамокаты": 0.005,
    "Электронные книги": 0.07,
    "Электронные музыкальные инструмент": 0.155,
    "Прочие авт товары": 0.205,
}

COMMISSIONS_BY_SUBCAT = {
    "Автотовары": 0.205,
    "Товары для школы": 0.235,
    "Транспортные средства": 0.005,
    "Цифровая техника": 0.07,
    "Электроника": 0.155,
}

COMMISSIONS_DEFAULT = 0.15

# ──────────────────────────────────────────────────────────────

@st.cache_resource
def init_db():
    conn = sqlite3.connect("mvideo.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS ai_cache (name TEXT PRIMARY KEY, category TEXT, rate REAL)")
    conn.commit()
    return conn

conn = init_db()

def lookup_commission(name: str) -> tuple[str, float]:
    """Ищет комиссию по 3 уровням: Группа Товаров → Планнейм → Подкатегория."""
    name_lower = name.lower()
    # Уровень 1: Группа Товаров
    for key, rate in COMMISSIONS_BY_GROUP.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return key, rate
    # Уровень 2: Планнейм
    for key, rate in COMMISSIONS_BY_PLAN.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return key, rate
    # Уровень 3: Подкатегория
    for key, rate in COMMISSIONS_BY_SUBCAT.items():
        if key.lower() in name_lower:
            return key, rate
    return "Others", COMMISSIONS_DEFAULT

def get_ai_category(product_name, api_key=None):
    c = conn.cursor()
    c.execute("SELECT category, rate FROM ai_cache WHERE name=?", (product_name,))
    cached = c.fetchone()
    if cached:
        return cached[0], cached[1]

    category, rate = lookup_commission(product_name)

    if api_key and category == "Others":
        try:
            client = OpenAI(api_key=api_key)
            all_keys = list(COMMISSIONS_BY_GROUP.keys()) + list(COMMISSIONS_BY_PLAN.keys())
            prompt = (
                f"Определи наиболее подходящую группу товара '{product_name}' из списка: "
                f"{', '.join(all_keys[:60])}. Ответь только точным названием из списка."
            )
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                timeout=5,
            )
            ai_cat = response.choices[0].message.content.strip()
            if ai_cat in COMMISSIONS_BY_GROUP:
                category, rate = ai_cat, COMMISSIONS_BY_GROUP[ai_cat]
            elif ai_cat in COMMISSIONS_BY_PLAN:
                category, rate = ai_cat, COMMISSIONS_BY_PLAN[ai_cat]
        except Exception:
            pass

    c.execute("INSERT OR REPLACE INTO ai_cache VALUES (?, ?, ?)", (product_name, category, rate))
    conn.commit()
    return category, rate

# ──────────────────────────────────────────────────────────────

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

                category, comm_rate = get_ai_category(name, openai_key)
                logistics = calculate_logistics(l, w, h, weight)

                ref_fee = price * comm_rate
                acq_cost = price * (acquiring / 100)
                early_cost = price * (early_payout / 100)
                tax_cost = price * 0.06 if tax_system == "УСН Доходы (6%)" else 0

                profit = price - (cost + ref_fee + logistics + acq_cost + early_cost + tax_cost)
                margin_pct = (profit / price) * 100 if price > 0 else 0.0

                rec_price = find_target_price(cost, logistics, comm_rate, acquiring, early_payout, tax_system, target_margin)

                results.append({
                    "Артикул": sku,
                    "Наименование": name,
                    "Категория": category,
                    "Комиссия %": round(comm_rate * 100, 2),
                    "Тек. Цена": price,
                    "Маржа %": round(margin_pct, 2),
                    "Маржа": margin_pct / 100.0,
                    "Прибыль": round(profit, 2),
                    "Цель Маржа %": target_margin,
                    "Рек. Цена": round(rec_price, 0),
                })
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
                "Комиссия %": st.column_config.NumberColumn("Комиссия %", format="%.2f"),
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
