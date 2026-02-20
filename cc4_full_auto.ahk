#NoEnv
#SingleInstance Force
SetTitleMatchMode, 2
CoordMode, Mouse, Screen 
CoordMode, ToolTip, Screen
SendMode Event
SetKeyDelay, 40, 40 
SetMouseDelay, 50 
SetWorkingDir %A_ScriptDir%

; ================================
; НАСТРОЙКИ
; ================================
CC4_TITLE := "Character Creator 4"
WORK_DIR  := "C:\CC4_Pipeline\"
TODO_FILE := WORK_DIR . "todo.json"
CURRENT_JPG := WORK_DIR . "current.jpg" 
PYTHON_SCRIPT := WORK_DIR . "cc4_apply_once.py"

; Паузы
WAIT_AFTER_SCRIPT  := 500
WAIT_AFTER_APPLY   := 3000 
WAIT_AFTER_EXPORT  := 800
CHECK_INTERVAL     := 200

Running := false

; Переменные для координат
PosX_Script := 0, PosY_Script := 0
PosX_Load   := 0, PosY_Load   := 0
PosX_Export := 0, PosY_Export := 0

; ================================
; РЕЖИМ ОБУЧЕНИЯ (ЗАПИСЬ ТОЧЕК)
; ================================

^!1:: 
MouseGetPos, PosX_Script, PosY_Script
ToolTip, [1] Точка 'Script' записана
SetTimer, RemoveTip, -1500
return

^!2:: 
MouseGetPos, PosX_Load, PosY_Load
ToolTip, [2] Точка 'Load' записана
SetTimer, RemoveTip, -1500
return

^!4:: 
MouseGetPos, PosX_Export, PosY_Export
ToolTip, [4] Точка 'Export' записана
SetTimer, RemoveTip, -1500
return

; ================================
; УПРАВЛЕНИЕ ЦИКЛОМ
; ================================

^!9:: 
if (!PosX_Script or !PosX_Load or !PosX_Export) {
    MsgBox, 48, Ошибка, Сначала запиши все 3 точки (Ctrl+Alt+1, 2, 4)!
    return
}

Running := !Running
ToolTip % "CC4 AUTO: " . (Running ? "СТАРТ" : "СТОП")
SetTimer, RemoveTip, -1500

if (Running)
    SetTimer MainLoop, %CHECK_INTERVAL%
else
    SetTimer MainLoop, Off
return

^!0::ExitApp 

RemoveTip:
ToolTip
return

; ================================
; ОСНОВНОЙ ЦИКЛ
; ================================
MainLoop:

if (!Running)
    return

if (!FileExist(TODO_FILE))
    return

if !WinExist(CC4_TITLE)
    return

WinActivate
WinWaitActive, %CC4_TITLE%, , 2
if ErrorLevel
    return

; 1) Клик по меню Script
Click, %PosX_Script%, %PosY_Script%
Sleep %WAIT_AFTER_SCRIPT%

; 2) Клик по Load Python
Click, %PosX_Load%, %PosY_Load%

; -- ОБРАБОТКА ОКНА "ОТКРЫТИЕ" (для Python) --
WinWait, ahk_class #32770, , 5 
if (!ErrorLevel) 
{
    WinActivate, ahk_class #32770
    WinWaitActive, ahk_class #32770, , 2
    Sleep 200
    ClipSaved := ClipboardAll 
    Clipboard := PYTHON_SCRIPT
    Send, ^v
    Sleep 200
    Send, {Enter}
    Clipboard := ClipSaved 
}
else
{
    return 
}

; 3) Ждем выполнения Python скрипта в CC4
Sleep %WAIT_AFTER_APPLY%

; -- БЕЗОПАСНОЕ УДАЛЕНИЕ СТАРОГО РЕНДЕРА --
if FileExist(CURRENT_JPG)
{
    Loop, 10 ; Делаем максимум 10 попыток с паузами
    {
        FileDelete, %CURRENT_JPG%
        if (!ErrorLevel) ; ErrorLevel 0 означает успех
            break
        
        ToolTip, Ждем пока Python отпустит картинку...
        Sleep 500
    }
    ToolTip ; Убираем подсказку
}

; 4) Клик по Export
Click, %PosX_Export%, %PosY_Export%

; -- ОБРАБОТКА ОКНА "СОХРАНЕНИЕ" (для картинки) --
WinWait, ahk_class #32770, , 5 
if (!ErrorLevel) 
{
    WinActivate, ahk_class #32770
    WinWaitActive, ahk_class #32770, , 2
    Sleep 200
    
    ; Вставляем полный путь к картинке
    ClipSaved := ClipboardAll 
    Clipboard := CURRENT_JPG
    Send, ^v
    Sleep 200
    Send, {Enter}
    Clipboard := ClipSaved 
}

Sleep %WAIT_AFTER_EXPORT%

; --- ГАШЕНИЕ ПРОСМОТРЩИКА ФОТО ---
Sleep 1500 ; Даем 1.5 секунды, чтобы винда точно успела запустить просмотрщик

; Универсальный способ: ищем любое окно, в названии которого есть "current.jpg"
IfWinExist, current.jpg
{
    WinGet, exeName, ProcessName, current.jpg
    ; Проверяем, что это не процесс самого CC4 (защита от случайного закрытия)
    if (exeName != "CharacterCreator.exe" && exeName != "Character Creator 4.exe")
    {
        WinClose, current.jpg
    }
}

; Прямое убийство стандартных просмотрщиков Windows 10/11 (как резервная страховка)
IfWinExist, ahk_exe Microsoft.Photos.exe
    WinClose, ahk_exe Microsoft.Photos.exe
IfWinExist, ahk_exe PhotosApp.exe
    WinClose, ahk_exe PhotosApp.exe

; Возвращаем фокус обратно на CC4 для следующей итерации
WinActivate, %CC4_TITLE%

return