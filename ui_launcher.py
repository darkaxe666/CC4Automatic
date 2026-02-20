# -*- coding: utf-8 -*-
import os
import sys
import json
import shutil
import threading
import subprocess
import time
import customtkinter as ctk
from tkinter import filedialog
from PIL import Image

# ================================
# НАСТРОЙКИ ПУТЕЙ
# ================================
WORK_DIR = "C:/CC4_Pipeline/"
REF_IMG = os.path.join(WORK_DIR, "ref.jpg")
CUR_IMG = os.path.join(WORK_DIR, "current.jpg")
INITIAL_IMG = os.path.join(WORK_DIR, "initial.jpg")
FINAL_IMG = os.path.join(WORK_DIR, "final.jpg")
CONFIG_FILE = os.path.join(WORK_DIR, "config.json")
ART_DIRECTOR_SCRIPT = os.path.join(WORK_DIR, "art_director.py")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class CC4ArtDirectorUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Art Director for CC4")
        self.geometry("950x700")
        self.resizable(False, False)

        self.is_running = False
        self.current_ready = False
        self.process = None # Переменная для хранения процесса art_director

        # --- ЛЕВАЯ ПАНЕЛЬ ---
        self.left_frame = ctk.CTkFrame(self, width=400)
        self.left_frame.pack(side="left", fill="y", padx=10, pady=10)

        self.lbl_ref_title = ctk.CTkLabel(self.left_frame, text="Референс (ref.jpg)", font=("Arial", 14, "bold"))
        self.lbl_ref_title.pack(pady=(10, 0))
        self.lbl_ref_img = ctk.CTkLabel(self.left_frame, text="Нет изображения", width=256, height=256, fg_color="gray20")
        self.lbl_ref_img.pack(pady=10)

        self.lbl_cur_title = ctk.CTkLabel(self.left_frame, text="Результат CC4", font=("Arial", 14, "bold"))
        self.lbl_cur_title.pack(pady=(10, 0))
        self.lbl_cur_img = ctk.CTkLabel(self.left_frame, text="Ожидание...", width=256, height=256, fg_color="gray20")
        self.lbl_cur_img.pack(pady=10)

        self.compare_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.compare_frame.pack(pady=5)
        self.btn_show_initial = ctk.CTkButton(self.compare_frame, text="Показать ДО", width=120, state="disabled", command=lambda: self.show_preview(INITIAL_IMG))
        self.btn_show_initial.pack(side="left", padx=5)
        self.btn_show_final = ctk.CTkButton(self.compare_frame, text="Показать ПОСЛЕ", width=120, state="disabled", command=lambda: self.show_preview(FINAL_IMG))
        self.btn_show_final.pack(side="left", padx=5)

        # --- ПРАВАЯ ПАНЕЛЬ ---
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)

        self.btn_load_ref = ctk.CTkButton(self.right_frame, text="1. Загрузить Референс", command=self.load_reference)
        self.btn_load_ref.pack(pady=(20, 10), fill="x", padx=20)

        self.mode_var = ctk.StringVar(value=self.get_current_mode())
        self.radio_body = ctk.CTkRadioButton(self.right_frame, text="Режим: ТЕЛО", variable=self.mode_var, value="body", command=self.update_config)
        self.radio_body.pack(pady=5, anchor="w", padx=20)
        self.radio_face = ctk.CTkRadioButton(self.right_frame, text="Режим: ЛИЦО", variable=self.mode_var, value="face", command=self.update_config)
        self.radio_face.pack(pady=5, anchor="w", padx=20)

        # Статусы
        self.lbl_ahk_status = ctk.CTkLabel(self.right_frame, text="🔍 Проверка AHK...", font=("Arial", 12, "bold"))
        self.lbl_ahk_status.pack(pady=(15, 0))

        self.lbl_status = ctk.CTkLabel(self.right_frame, text="❌ current.jpg не найден.", text_color="red", font=("Arial", 12, "bold"))
        self.lbl_status.pack(pady=(5, 15))

        # Блок кнопок управления
        self.control_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.control_frame.pack(fill="x", padx=20, pady=5)

        self.btn_start = ctk.CTkButton(self.control_frame, text="СТАРТ", fg_color="green", hover_color="darkgreen", command=self.start_pipeline, state="disabled")
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 5), ipady=5)

        self.btn_stop = ctk.CTkButton(self.control_frame, text="СТОП", fg_color="red", hover_color="darkred", command=self.stop_pipeline, state="disabled", width=80)
        self.btn_stop.pack(side="right", padx=(5, 0), ipady=5)

        # Консоль
        self.lbl_console = ctk.CTkLabel(self.right_frame, text="Логи работы ИИ:", anchor="w")
        self.lbl_console.pack(fill="x", padx=20, pady=(10, 0))
        self.console = ctk.CTkTextbox(self.right_frame, state="disabled", font=("Consolas", 11))
        self.console.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        if os.path.exists(REF_IMG):
            self.update_image_preview(REF_IMG, self.lbl_ref_img)

        self.watcher_thread = threading.Thread(target=self.background_watcher, daemon=True)
        self.watcher_thread.start()

    def log(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def load_reference(self):
        filepath = filedialog.askopenfilename(title="Выберите референс", filetypes=[("Image Files", "*.jpg *.jpeg *.png")])
        if filepath:
            shutil.copy(filepath, REF_IMG)
            self.update_image_preview(REF_IMG, self.lbl_ref_img)
            self.log(f"[UI] Референс загружен: {os.path.basename(filepath)}")

    def get_current_mode(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f).get("target", "body")
            except: pass
        return "body"

    def update_config(self):
        mode = self.mode_var.get()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                cfg["target"] = mode
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                self.log(f"[UI] Режим изменен на: {mode.upper()}")
            except: pass

    def update_image_preview(self, img_path, label_widget):
        try:
            img = Image.open(img_path)
            img.thumbnail((256, 256))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            label_widget.configure(image=ctk_img, text="")
            label_widget.image = ctk_img
        except: pass

    def show_preview(self, path):
        if os.path.exists(path):
            self.update_image_preview(path, self.lbl_cur_img)

    def is_ahk_running(self):
        """Проверяет через системную утилиту tasklist, запущен ли AutoHotkey"""
        try:
            output = subprocess.check_output('tasklist', shell=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return 'AutoHotkey' in output
        except:
            return False

    def background_watcher(self):
        """Следит за AHK и картинкой"""
        while True:
            # 1. Проверка AHK
            ahk_running = self.is_ahk_running()
            if ahk_running:
                self.lbl_ahk_status.configure(text="🟢 AHK скрипт запущен", text_color="green")
            else:
                self.lbl_ahk_status.configure(text="🔴 ВНИМАНИЕ: AHK не запущен!", text_color="red")

            # 2. Проверка картинки (только если не запущен пайплайн)
            if not self.is_running:
                if os.path.exists(CUR_IMG):
                    if not self.current_ready:
                        self.current_ready = True
                        self.lbl_status.configure(text="✅ current.jpg готов!", text_color="green")
                        self.btn_start.configure(state="normal")
                        self.update_image_preview(CUR_IMG, self.lbl_cur_img)
                else:
                    if self.current_ready:
                        self.current_ready = False
                        self.lbl_status.configure(text="❌ Жду current.jpg", text_color="red")
                        self.btn_start.configure(state="disabled")
            time.sleep(1.5)

    def start_pipeline(self):
        if not os.path.exists(CUR_IMG): return
        
        self.is_running = True
        self.btn_start.configure(state="disabled", text="Выполняется...")
        self.btn_stop.configure(state="normal") # Включаем кнопку СТОП
        self.btn_load_ref.configure(state="disabled")
        self.btn_show_initial.configure(state="disabled")
        self.btn_show_final.configure(state="disabled")
        
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

        shutil.copy(CUR_IMG, INITIAL_IMG)
        self.log("[UI] Исходное изображение сохранено (ДО).")

        threading.Thread(target=self.run_art_director, daemon=True).start()

    def stop_pipeline(self):
        """Жесткая остановка процесса"""
        if self.process:
            self.process.terminate()
            self.log("\n[UI] 🛑 ПРОЦЕСС ПРИНУДИТЕЛЬНО ОСТАНОВЛЕН ПОЛЬЗОВАТЕЛЕМ!")
            self.pipeline_finished()

    def run_art_director(self):
        python_exe = sys.executable 
        self.process = subprocess.Popen(
            [python_exe, "-u", ART_DIRECTOR_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in self.process.stdout:
            self.after(0, self.log, line.strip())
        
        self.process.wait()
        
        # Если скрипт не был убит вручную (returncode != 15/1), завершаем нормально
        if self.is_running: 
            self.after(0, self.pipeline_finished)

    def pipeline_finished(self):
        self.is_running = False
        self.btn_start.configure(state="normal", text="СТАРТ")
        self.btn_stop.configure(state="disabled")
        self.btn_load_ref.configure(state="normal")

        if os.path.exists(CUR_IMG):
            shutil.copy(CUR_IMG, FINAL_IMG)
            self.log("[UI] Финальный результат сохранен (ПОСЛЕ).")
            self.update_image_preview(FINAL_IMG, self.lbl_cur_img)
            self.btn_show_initial.configure(state="normal")
            self.btn_show_final.configure(state="normal")

if __name__ == "__main__":
    app = CC4ArtDirectorUI()
    app.mainloop()