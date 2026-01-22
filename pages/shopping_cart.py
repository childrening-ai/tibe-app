import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import json

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

st.title("🛒 書展掃碼比價 & 採購清單")
st.markdown("輸入 ISBN，自動抓取書本資訊並記錄到雲端試算表，家人同步看得到！")

# --- 設定區 ---
# ⚠️ 請確保這裡的名稱跟您的 Google 試算表名稱一模一樣
SHEET_NAME = "2026國際書展採購清單"

# --- 1. 連接 Google Sheets (雲端/本機 雙棲通用版) ---
@st.cache_resource
def connect_to_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    try:
        # 情況 A：在 Streamlit Cloud (使用 st.secrets)
        # 這是為了上傳後準備的
        if "gcp_service_account" in st.secrets:
            # 建立憑證字典
            creds_dict = dict(st.secrets["gcp_service_account"])
            
            # 修復 private_key 的換行符號問題 (Streamlit Cloud 的常見坑)
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        # 情況 B：在本機電腦 (使用 secrets.json 檔案)
        # 這是為了您現在測試用的
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
            
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet

    except Exception as e:
        # 如果連線失敗，回傳錯誤訊息，方便除錯
        print(f"連線錯誤: {e}")
        return None

# --- 2. 抓取書本資料 (Google Books API) ---
def get_book_info(isbn):
    if not isbn: return None
    
    # 清除 ISBN 中的橫槓或空白
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    
    try:
        response = requests.get(url)
        data = response.json()
        
        if "items" in data:
            info = data["items"][0]["volumeInfo"]
            return {
                "書名": info.get("title", "未知名稱"),
                "作者": ", ".join(info.get("authors", ["未知"])),
                "封面": info.get("imageLinks", {}).get("thumbnail", ""),
                "ISBN": clean_isbn,
                "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        else:
            return {"書名": "找不到這本書", "作者": "", "封面": "", "ISBN": clean_isbn}
    except:
        return None

# --- 主程式邏輯 ---

# A. 初始化連線
sheet = connect_to_sheet()

if not sheet:
    st.error(f"❌ 無法連接試算表！\n請檢查 Google Sheet 名稱是否為 `{SHEET_NAME}`，或是金鑰設定是否正確。")
    st.stop()

# B. 輸入區
col1, col2 = st.columns([1, 2])

with col1:
    st.info("👇 在此輸入 ISBN (未來可接掃描槍)")
    with st.form("isbn_form", clear_on_submit=True):
        isbn_input = st.text_input("ISBN 條碼", placeholder="例如: 978957...")
        submitted = st.form_submit_button("🔍 查詢與加入")

    if submitted and isbn_input:
        with st.spinner("正在搜尋書籍資料..."):
            book_data = get_book_info(isbn_input)
            
            if book_data and book_data['書名'] != "找不到這本書":
                st.success(f"已找到：{book_data['書名']}")
                st.image(book_data['封面'], width=100)
                
                # 寫入 Google Sheet
                # 欄位順序：時間, 書名, 作者, ISBN, 價格(預留), 購買狀態(預留)
                new_row = [
                    book_data['建檔時間'],
                    book_data['書名'],
                    book_data['作者'],
                    book_data['ISBN'],
                    "",     # 價格留白
                    "待購"   # 預設狀態
                ]
                sheet.append_row(new_row)
                st.toast("✅ 已成功加入雲端清單！")
                time.sleep(1) # 稍微等待一下讓資料寫入
                st.rerun()    # 重新整理畫面以顯示最新資料
                
            else:
                st.warning("找不到這本書的資料，請檢查 ISBN 是否正確。")

# C. 顯示清單區 (從雲端讀取)
st.divider()
st.subheader("📋 雲端同步清單")

# 讀取所有資料
try:
    records = sheet.get_all_records()
    if records:
        df = pd.DataFrame(records)
        
        # 顯示互動表格 (允許使用者在上面直接改價格或狀態)
        edited_df = st.data_editor(
            df, 
            use_container_width=True,
            num_rows="dynamic", # 允許新增/刪除行
            key="data_editor"
        )
        
        # 簡單算個數量
        st.metric("目前書籍數量", len(df))
    else:
        st.info("目前清單是空的，快去掃幾本書吧！")
        if st.button("🛠️ 建立預設標題列 (第一次使用請點我)"):
            header = ["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"]
            sheet.append_row(header)
            st.rerun()

except Exception as e:
    st.error(f"讀取資料失敗: {e}")