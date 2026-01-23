import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import time
import re
import urllib3

# 1. 頁面設定 (必須是第一行)
st.set_page_config(page_title="書展敗家診斷版", page_icon="🚑", layout="wide")

# 設定區
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 2. 連線功能 (移除 Cache，確保每次都連線) ---
def connect_to_spreadsheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(SHEET_NAME)
        return spreadsheet
    except Exception as e:
        st.error(f"❌ 連線失敗: {e}")
        return None

# --- 3. 取得分頁 (包含暴力初始化) ---
def get_or_create_sheet(spreadsheet, user_id):
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    if not safe_id: return None
    
    try:
        sheet = spreadsheet.worksheet(safe_id)
        return sheet
    except gspread.WorksheetNotFound:
        # 如果找不到，建立新的，並給它 20 行空間
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=20, cols=10)
            # 強制寫入標題
            sheet.update(range_name='A1', values=[["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"]])
            return sheet
        except Exception as e:
            st.error(f"❌ 建立分頁失敗: {e}")
            return None

# --- 4. 爬蟲 (保留原本功能) ---
def clean_isbn_func(isbn_raw):
    return str(isbn_raw).strip().replace("-", "").replace(" ", "").replace("\n", "").replace("\t", "") if isbn_raw else ""

def search_google_books(isbn):
    clean_isbn = clean_isbn_func(isbn)
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url, timeout=3).json()
        if "items" in res:
            info = res["items"][0]["volumeInfo"]
            return {
                "書名": info.get("title", ""),
                "作者": ", ".join(info.get("authors", [])),
                "封面": info.get("imageLinks", {}).get("thumbnail", ""),
                "found": True
            }
    except: pass
    return {"found": False}

def smart_book_search(isbn_input):
    if not isbn_input: return None
    clean_isbn = clean_isbn_func(isbn_input)
    result = {"書名": "", "作者": "", "ISBN": clean_isbn, "封面": "", "定價": "", "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "found": False}
    g_data = search_google_books(clean_isbn)
    if g_data["found"]:
        result.update(g_data)
        result["found"] = True
    return result

# --- 介面開始 ---
st.title("🚑 書展購物車 (強制寫入除錯版)")

# 側邊欄登入
st.sidebar.title("登入")
user_id = st.sidebar.text_input("輸入暱稱 (例如 Test01)")

if not user_id:
    st.warning("請先在左側輸入暱稱")
    st.stop()

# 1. 嘗試連線
ss = connect_to_spreadsheet()
if not ss:
    st.stop()

# 2. 取得分頁
sheet = get_or_create_sheet(ss, user_id)
if not sheet:
    st.error("無法取得分頁，請檢查 Google Sheet 權限。")
    st.stop()

st.success(f"✅ 已連線至分頁：{user_id}")

# --- 診斷區 (直接顯示 Sheet 裡的原始資料) ---
with st.expander("🕵️‍♂️ 檢視 Google Sheet 原始資料 (Debug)", expanded=False):
    raw_data = sheet.get_all_values()
    st.write(f"目前總行數: {len(raw_data)}")
    st.write(raw_data)

# --- A. 新增書籍 (最單純的寫入) ---
col1, col2 = st.columns([1, 2])
with col1:
    isbn_input = st.text_input("輸入 ISBN", key="isbn_input")
    if st.button("🔍 查詢"):
        if isbn_input:
            res = smart_book_search(isbn_input)
            st.session_state.temp_res = res
        else:
            st.warning("請輸入 ISBN")

# 顯示搜尋結果與寫入按鈕
if 'temp_res' in st.session_state and st.session_state.temp_res:
    res = st.session_state.temp_res
    st.info(f"找到：{res['書名']}")
    
    with st.form("add_book_form"):
        f_title = st.text_input("書名", value=res['書名'])
        f_author = st.text_input("作者", value=res['作者'])
        f_price = st.text_input("價格", value=res['定價'])
        
        submit = st.form_submit_button("➕ 寫入 Google Sheet")
        
        if submit:
            # 準備資料
            new_row = [
                res['建檔時間'],
                f_title,
                f_author,
                res['ISBN'],
                f_price,
                "待購"
            ]
            
            try:
                # 🔥 這裡使用最暴力的 append_row，不做任何檢查
                sheet.append_row(new_row)
                st.success(f"✅ 成功寫入：{f_title}")
                # 清除暫存並重整
                del st.session_state.temp_res
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"❌ 寫入失敗: {e}")

st.divider()

# --- B. 讀取清單 (最單純的讀取) ---
st.subheader("📋 目前清單")

try:
    # 重新讀取資料
    data = sheet.get_all_values()
    
    # 如果只有少於 1 行 (代表連標題都沒有)
    if len(data) < 1:
        st.warning("⚠️ 試算表是完全空的 (連標題都沒有)。")
        if st.button("🛠️ 建立標題列"):
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            st.rerun()
            
    # 如果有資料
    else:
        # 第一列是標題
        headers = data[0]
        # 後面是內容
        rows = data[1:]
        
        if rows:
            df = pd.DataFrame(rows, columns=headers)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("目前沒有書籍資料。")

except Exception as e:
    st.error(f"讀取顯示失敗: {e}")