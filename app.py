import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime

# 1. 頁面基本設定
st.set_page_config(
    page_title="2026 國際書展小幫手",
    page_icon="📅",
    layout="wide"
)

# --- 設定區 ---
# 這是您的 Google Sheet 檔案名稱
SHEET_NAME = "2026國際書展行事曆"

# 🔥 未來擴充重點：這裡填入所有您想讀取的分頁名稱
# 例如：["國際書展", "親子天下", "信誼基金會"]
# 程式會自動把這些分頁的資料抓下來，並依日期合併在一起顯示
WORKSHEETS_TO_LOAD = ["國際書展"] 

# --- 2. 連線與資料讀取函式 ---
@st.cache_data(ttl=300) # 快取 5 分鐘
def load_all_calendar_data():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        # 讀取 Secrets
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        
        client = gspread.authorize(creds)
        
        try:
            spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            return None, f"找不到檔案：{SHEET_NAME}，請確認 Google Drive 檔案名稱正確。"

        all_frames = []
        errors = []

        # 🔥 迴圈讀取每一個指定的分頁
        for ws_name in WORKSHEETS_TO_LOAD:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data = worksheet.get_all_values()
                
                if len(data) < 2:
                    continue # 空分頁跳過
                
                header = data[0]
                rows = data[1:]
                
                # 轉成 DataFrame
                df = pd.DataFrame(rows, columns=header)
                
                # 自動加入「來源」欄位，讓使用者知道這是哪個單位的活動
                df['來源'] = ws_name 
                
                # 簡單清洗欄位名稱 (移除空白)
                df.columns = [c.strip() for c in df.columns]
                
                all_frames.append(df)
                
            except gspread.WorksheetNotFound:
                errors.append(f"找不到分頁：{ws_name}")
            except Exception as e:
                errors.append(f"讀取 {ws_name} 失敗: {e}")

        if not all_frames:
            return None, f"沒有讀取到任何資料。錯誤訊息：{errors}"
            
        # 合併所有 DataFrame
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"

    except Exception as e:
        return None, f"連線系統錯誤: {e}"

# --- 3. 主程式介面 ---

st.title("📅 2026 國際書展活動行事曆")
st.caption("匯集官方主場次與各出版社攤位活動，一站式查詢！")

# 讀取資料
df, msg = load_all_calendar_data()

if df is None or df.empty:
    st.error("⚠️ 資料讀取失敗")
    with st.expander("查看詳細錯誤"):
        st.write(msg)
    st.stop()

# --- 資料前處理 ---
# 檢查必要欄位 (容許部分欄位缺失，但日期時間一定要有)
if '日期' not in df.columns or '活動名稱' not in df.columns:
    st.error("❌ 資料表缺少「日期」或「活動名稱」欄位，請檢查 Google Sheet。")
    st.stop()

# 確保時間欄位存在，若無則補空
if '時間' not in df.columns: df['時間'] = ""
if '地點' not in df.columns: df['地點'] = ""
if '講者' not in df.columns: df['講者'] = ""
if '類型' not in df.columns: df['類型'] = "一般"
if '備註' not in df.columns: df['備註'] = ""

# --- 側邊欄：篩選器 ---
st.sidebar.header("🔍 活動篩選")

# 0. 來源篩選 (新增！)
all_sources = sorted(list(set(df['來源'].unique())))
selected_sources = st.sidebar.multiselect("🏢 選擇活動來源", all_sources, default=all_sources)

# 1. 地點篩選
all_locations = sorted(list(set(df['地點'].unique())))
selected_locs = st.sidebar.multiselect("📍 選擇地點", all_locations, default=all_locations)

# 2. 類型篩選
all_types = sorted(list(set(df['類型'].unique())))
selected_types = st.sidebar.multiselect("🏷️ 選擇類型", all_types, default=all_types)

# 3. 關鍵字
keyword = st.sidebar.text_input("🔎 搜尋活動/講者", "")

# 執行篩選
filtered_df = df[
    (df['來源'].isin(selected_sources)) &
    (df['地點'].isin(selected_locs)) & 
    (df['類型'].isin(selected_types))
]

if keyword:
    filtered_df = filtered_df[
        filtered_df['活動名稱'].str.contains(keyword, case=False) | 
        filtered_df['講者'].str.contains(keyword, case=False)
    ]

# --- 4. 顯示行事曆 (Tabs + Cards) ---

# 取得所有不重複的日期並排序
# 注意：這裡假設日期格式是 "2026-02-xx" 這樣才能正確排序
unique_dates = sorted(list(set(filtered_df['日期'].unique())))

if not unique_dates:
    st.info("📭 查無符合條件的活動，請調整篩選條件。")
else:
    # 建立分頁
    tabs = st.tabs([f"📅 {d[5:]}" for d in unique_dates]) # d[5:] 只顯示 月-日，比較簡潔 (例如 02-04)

    for i, date_str in enumerate(unique_dates):
        with tabs[i]:
            day_events = filtered_df[filtered_df['日期'] == date_str]
            
            # 依時間排序
            day_events = day_events.sort_values(by='時間')

            st.caption(f"共 {len(day_events)} 場活動")
            
            for _, row in day_events.iterrows():
                # 裝飾顏色
                type_color = "blue"
                if "簽書" in row['類型']: type_color = "green"
                elif "講座" in row['類型']: type_color = "orange"
                elif "直播" in row['類型']: type_color = "red"
                
                # 來源標籤樣式
                source_badge = f"【{row['來源']}】" if row['來源'] != "國際書展" else "【官方】"

                with st.container(border=True):
                    # 第一排：時間 | 來源 | 類型
                    c1, c2 = st.columns([1, 4])
                    with c1:
                        st.markdown(f"**🕒 {row['時間']}**")
                    with c2:
                        # 顯示來源與類型
                        st.markdown(f"**{source_badge}** :{type_color}[{row['類型']}]")
                    
                    # 第二排：標題
                    st.markdown(f"### {row['活動名稱']}")
                    
                    # 第三排：講者與地點
                    c3, c4 = st.columns(2)
                    with c3:
                        if row['講者']: st.markdown(f"**🎤 講者：** {row['講者']}")
                    with c4:
                        if row['地點']: st.markdown(f"**📍 地點：** {row['地點']}")
                    
                    # 第四排：備註
                    if row['備註']:
                        st.caption(f"💡 {row['備註']}")