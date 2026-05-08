# Sounduct — Contexto del Proyecto

## ¿Qué es?
Sounduct es un gestor de descargas de audio para DJs. 
Detecta archivos de audio que caen en una carpeta origen (LA CASA), 
pregunta al usuario a qué subcarpeta van mediante un popup, 
y sincroniza automáticamente el contenido con un pendrive.

## Stack
- Python + watchdog (detección de archivos)
- PyQt6 + HTML/CSS (interfaz de popups)
- PollingObserver (compatibilidad Windows)

## Rutas del sistema
- LA CASA: C:\Users\Lorenzo\Desktop\LA CASA
- PENDRIVE: E:\
- Script: C:\Users\Lorenzo\Desktop\Sounduct\housero.py
- HTMLs: popup_carpeta.html, popup_sync.html, styles.css (misma carpeta que el script)

## Archivos del proyecto
- housero.py — lógica principal
- popup_carpeta.html — popup de selección de carpeta destino
- popup_sync.html — popup de sincronización con pendrive
- styles.css — estilos compartidos (dark mode, acento ámbar)

## Comportamiento actual
- Descarga detectada → popup con carpetas dinámicas → archivo movido al destino
- Archivos no-audio → van a C:\Users\Lorenzo\Downloads automático
- PD conectado → copia automática al instante
- PD desconectado → diff al reconectar
- Delete/move/rename en LA CASA → se replica en PD
- Diff inteligente por tamaño de archivo
- Ignora System Volume Information

## Formatos de audio soportados
.mp3, .wav, .aiff, .flac, .ogg, .m4a

## Pendiente de pulir
- Error `Cannot read properties of null` en terminal
- System tray — correr sin terminal visible

## Features a implementar
- Historial de descargas
- Presets de evento — filtrar carpetas por pendrive/contexto
- Integración rekordbox/Serato
- Soporte Mac
- Sync en la nube
- Freemium / planes pago
- Empaquetado como .exe instalable

## Modelo de negocio
- Distribución gratuita inicial para tracción en comunidad DJ
- Planes pago una vez establecido (~5 USD/mes)
- Nicho: DJs activos que gestionan música fuera de los ecosistemas DJ

## Nombre del producto
Sounduct — nombre libre, sin competencia directa identificada