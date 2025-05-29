from flask import Flask
from statsmodels.tsa.arima.model import ARIMA
import pandas as pd
from pmdarima import auto_arima
import requests
import threading
import traceback
import time
import pytz
import warnings
import os

warnings.filterwarnings("ignore", category=FutureWarning)

app = Flask(__name__)

# === KONFIGURASI ===
TOKEN = "7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk"
CHAT_ID = "1027769170"
CHANNEL_ID = "2761831"
TIMEZONE = pytz.timezone("Asia/Makassar")

# === STATE NOTIFIKASI ===
last_status = ""
last_sent_time = 0

# === AMBIL DATA ===
def ambil_data_thingspeak(jumlah_data=100):
    try:
        timestamp = int(time.time())
        url = f"https://api.thingspeak.com/channels/2761831/feeds.csv?results={jumlah_data}&_={timestamp}"
        df = pd.read_csv(url)
        df.rename(columns={'field1': 'pH', 'field2': 'suhu', 'created_at': 'waktu'}, inplace=True)
        df['waktu'] = pd.to_datetime(df['waktu'], utc=True).dt.tz_convert(TIMEZONE)
        df['pH'] = pd.to_numeric(df['pH'], errors='coerce')
        df['suhu'] = pd.to_numeric(df['suhu'], errors='coerce')
        df = df[['waktu', 'pH', 'suhu']].dropna()
        return df
    except Exception as e:
        print("❌ Gagal ambil data:", e)
        return pd.DataFrame()

# === TELEGRAM ===
def kirim_telegram(pesan):
    try:
        url = f"https://api.telegram.org/bot7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": pesan}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("📤 Telegram dikirim.")
        else:
            print("⚠️ Gagal kirim:", response.text)
    except Exception as e:
        print("❌ Error kirim Telegram:", e)

# === RULE BASE ===
def cek_rulebase(ph, suhu):
    if ph <= 6.6 or ph >= 8.4 or suhu <= 26.5 or suhu >= 29.5:
        return "🚨 Air mendekati ambang batas, harap melakukan pengecekkan kondisi air"
    return "✅ Air dalam kondisi normal"

# === DETEKSI + PREDIKSI + NOTIF ===
def deteksi_dan_prediksi(df):
    global last_status, last_sent_time
    try:
        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH'].dropna()
        data_suhu = df['suhu'].dropna()
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        if len(data_ph) < 30 or len(data_suhu) < 30:
            print("⚠️ Data tidak cukup.")
            return

        model_ph = ARIMA(data_ph, order=(9,1,4)).fit()
        model_suhu = ARIMA(data_suhu, order=(5,1,2)).fit()

        pred_ph = model_ph.predict(n_periods=60).tolist()
        pred_suhu = model_suhu.predict(n_periods=60).tolist()

        ph_60 = pred_ph[59]
        suhu_60 = pred_suhu[59]
        waktu_pred_60 = waktu_terakhir + pd.Timedelta(minutes=60)

        status = cek_rulebase(ph_60, suhu_60)
        waktu_sekarang = time.time()

        if status != last_status or (status == last_status and waktu_sekarang - last_sent_time >= 600):
            if "🚨" in status:
                pesan = (
                    f"{status}\n"
                    f"📍 Waktu Aktual: {waktu_terakhir.strftime('%H:%M:%S')} WITA\n\n"
                    f"pH: {aktual_ph:.2f} | Suhu: {aktual_suhu:.2f}°C\n\n"
                    f"🔮 Prediksi 1 Jam → pH: {ph_60:.2f} | Suhu: {suhu_60:.2f}°C @ {waktu_pred_60.strftime('%H:%M:%S')} WITA"
                )
                kirim_telegram(pesan)
                last_status = status
                last_sent_time = waktu_sekarang
            else:
                print("✅ Kondisi normal, tidak kirim pesan.")
        else:
            print("⏳ Menunggu kondisi berubah atau 10 menit berlalu.")
    except Exception:
        traceback.print_exc()

# === LOOP STABIL ===
def loop_monitoring():
    while True:
        try:
            df = ambil_data_thingspeak(60)
            if not df.empty:
                deteksi_dan_prediksi(df)
        except Exception as e:
            print("❌ Error di loop:", e)
        time.sleep(60)

# === WEB ===
@app.route('/')
def index():
    try:
        df = ambil_data_thingspeak(60)
        if df.empty:
            return "<p>⚠️ Data kosong.</p>"

        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH']
        data_suhu = df['suhu']
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        model_ph = ARIMA(data_ph, order=(9,1,4)).fit()
        model_suhu = ARIMA(data_suhu, order=(5,1,2)).fit()

        pred_ph = model_ph.predict(n_periods=60).tolist()
        pred_suhu = model_suhu.predict(n_periods=60).tolist()

        ph_60 = pred_ph[59]
        suhu_60 = pred_suhu[59]
        waktu_pred_60 = waktu_terakhir + pd.Timedelta(minutes=60)

        status = cek_rulebase(ph_60, suhu_60)

        return f"""
        <h2>📊 Monitoring Kualitas Air</h2>
        <ul>
            <li>🕒 Waktu Aktual: <b>{waktu_terakhir.strftime('%Y-%m-%d %H:%M:%S')} (WITA)</b></li>
            <li>📌 Aktual → pH: <b>{aktual_ph:.2f}</b> | Suhu: <b>{aktual_suhu:.2f}°C</b></li>
            <li>🔮 Prediksi 1 Jam → pH: <b>{ph_60:.2f}</b> | Suhu: <b>{suhu_60:.2f}°C</b> @ {waktu_pred_60.strftime('%H:%M:%S')}</li>
            <li>📋 Status Prediksi: <b>{status}</b></li>
        </ul>
        """
    except Exception:
        traceback.print_exc()
        return "<p>❌ Terjadi error saat prediksi.</p>"

# === JALANKAN APLIKASI ===
if __name__ == '__main__':
    threading.Thread(target=loop_monitoring, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
