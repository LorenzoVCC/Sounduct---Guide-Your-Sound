import shutil
import os
import sys
import time
import json
import threading
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

from PyQt6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter
from PyQt6.QtCore import QUrl, pyqtSlot, QObject, pyqtSignal, QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineScript
from PyQt6.QtCore import Qt

# ──────────────────────────────────────────────
#  CONFIG PERSISTENTE
# ──────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH  = os.path.join(BASE_DIR, "config.json")
HTML_CARPETA = os.path.join(BASE_DIR, "popup_carpeta.html")
HTML_SYNC    = os.path.join(BASE_DIR, "popup_sync.html")
HTML_SETTINGS= os.path.join(BASE_DIR, "popup_settings.html")

CONFIG_DEFAULT = {
    "carpeta_descargas": os.path.join(os.path.expanduser("~"), "Downloads"),
    "carpeta_biblioteca": r"C:\Users\Lorenzo\Desktop\LA CASA",
    "carpeta_pd": r"E:\\"
}

def cargar_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                # rellenar keys faltantes con defaults
                for k, v in CONFIG_DEFAULT.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except Exception:
            pass
    return CONFIG_DEFAULT.copy()

def guardar_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# Config global (mutable en runtime)
_config = cargar_config()

def get_descargas():   return _config["carpeta_descargas"]
def get_biblioteca():  return _config["carpeta_biblioteca"]
def get_pd():          return _config["carpeta_pd"]

# ──────────────────────────────────────────────
#  CONSTANTES
# ──────────────────────────────────────────────
AUDIO_FORMATOS = ('.mp3', '.wav', '.aiff', '.flac', '.ogg', '.m4a')
CHECK_PD_CADA  = 10

# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def pd_conectado():
    return os.path.isdir(get_pd())

def es_audio(path):
    return os.path.splitext(path)[1].lower() in AUDIO_FORMATOS

def relativo(path):
    return os.path.relpath(path, get_biblioteca())

def esperar_archivo_completo(path, espera=3, intentos=60):
    tamano_anterior = -1
    for _ in range(intentos):
        try:
            tamano_actual = os.path.getsize(path)
        except Exception:
            return False
        if tamano_actual == tamano_anterior and tamano_actual > 0:
            return True
        tamano_anterior = tamano_actual
        time.sleep(espera)
    return False

def listar_carpetas():
    carpetas = ["/ Raíz"]
    try:
        for entry in sorted(os.scandir(get_biblioteca()), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith('.'):
                carpetas.append(entry.name)
    except Exception as e:
        print(f"[ERROR] Listando carpetas: {e}")
    return carpetas

# ──────────────────────────────────────────────
#  DIFF
# ──────────────────────────────────────────────
def calcular_diff():
    copiar, borrar = [], []
    casa = {}
    for raiz, _, archivos in os.walk(get_biblioteca()):
        for nombre in archivos:
            path = os.path.join(raiz, nombre)
            rel  = os.path.relpath(path, get_biblioteca())
            try: casa[rel] = os.path.getsize(path)
            except: pass
    pd_files = {}
    for raiz, _, archivos in os.walk(get_pd()):
        if 'System Volume Information' in raiz:
            continue
        for nombre in archivos:
            path = os.path.join(raiz, nombre)
            rel  = os.path.relpath(path, get_pd())
            try: pd_files[rel] = os.path.getsize(path)
            except: pass
    for rel, size in casa.items():
        if rel not in pd_files or pd_files[rel] != size:
            copiar.append(rel)
    for rel in pd_files:
        if rel not in casa:
            borrar.append(rel)
    return copiar, borrar

def _limpiar_carpetas_vacias(dirpath):
    while True:
        try:
            if os.path.isdir(dirpath) and not os.listdir(dirpath):
                if os.path.abspath(dirpath) == os.path.abspath(get_pd()): break
                os.rmdir(dirpath)
                dirpath = os.path.dirname(dirpath)
            else: break
        except: break

def pd_copy(rel):
    src = os.path.join(get_biblioteca(), rel)
    dst = os.path.join(get_pd(), rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[PD] Copiado: {rel}")

def pd_delete(rel):
    dst = os.path.join(get_pd(), rel)
    if os.path.isfile(dst): os.remove(dst)
    elif os.path.isdir(dst): shutil.rmtree(dst)
    _limpiar_carpetas_vacias(os.path.dirname(dst))

def pd_move(rel_src, rel_dst):
    src = os.path.join(get_pd(), rel_src)
    dst = os.path.join(get_pd(), rel_dst)
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        _limpiar_carpetas_vacias(os.path.dirname(src))

def pd_rename_dir(rel_src, rel_dst):
    src = os.path.join(get_pd(), rel_src)
    dst = os.path.join(get_pd(), rel_dst)
    if os.path.isdir(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)

# ──────────────────────────────────────────────
#  VENTANA BASE
# ──────────────────────────────────────────────
_CHANNEL_SCRIPT = """
(function() {
    function tryConnect() {
        if (typeof QWebChannel === 'undefined') {
            setTimeout(tryConnect, 50);
            return;
        }
        new QWebChannel(qt.webChannelTransport, function(ch) {
            window._api = ch.objects.api;
            if (typeof onApiReady === 'function') onApiReady(window._api);
        });
    }
    var s = document.createElement('script');
    s.src = 'qrc:///qtwebchannel/qwebchannel.js';
    s.onload = tryConnect;
    document.head.appendChild(s);
})();
"""

def crear_ventana(ancho, alto, api, frameless=True):
    view = QWebEngineView()
    view.setFixedSize(ancho, alto)
    flags = Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window
    if frameless:
        flags |= Qt.WindowType.FramelessWindowHint
    view.setWindowFlags(flags)

    channel = QWebChannel()
    channel.registerObject("api", api)
    view.page().setWebChannel(channel)

    script = QWebEngineScript()
    script.setName("qwebchannel_init")
    script.setSourceCode(_CHANNEL_SCRIPT)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    view.page().scripts().insert(script)

    view._channel = channel
    return view

# ──────────────────────────────────────────────
#  POPUP CARPETA
# ──────────────────────────────────────────────
class APICarpeta(QObject):
    cerrar_signal = pyqtSignal(str)

    def __init__(self, nombre_archivo):
        super().__init__()
        self._nombre = nombre_archivo

    @pyqtSlot(result=str)
    def getCarpetas(self):
        return json.dumps(listar_carpetas())

    @pyqtSlot(result=str)
    def getNombre(self):
        return self._nombre

    @pyqtSlot(str)
    def confirmar(self, carpeta):
        self.cerrar_signal.emit(carpeta)

    @pyqtSlot()
    def cancelar(self):
        self.cerrar_signal.emit("")


def abrir_popup_carpeta(nombre_archivo, callback):
    api  = APICarpeta(nombre_archivo)
    view = crear_ventana(650, 645, api)

    def on_cerrar(carpeta):
        view.close()
        callback(carpeta if carpeta else None)

    api.cerrar_signal.connect(on_cerrar)
    view.load(QUrl.fromLocalFile(HTML_CARPETA))
    view.show()
    view._keep = api


# ──────────────────────────────────────────────
#  POPUP SYNC
# ──────────────────────────────────────────────
class APISync(QObject):
    cerrar_signal   = pyqtSignal()
    progreso_signal = pyqtSignal(float, str)

    def __init__(self, copiar, borrar):
        super().__init__()
        self._copiar = copiar
        self._borrar = borrar

    @pyqtSlot(result=str)
    def getDatos(self):
        return json.dumps({
            "copiar": len(self._copiar),
            "borrar": len(self._borrar),
            "lista_borrar": self._borrar
        })

    @pyqtSlot()
    def ahora_no(self):
        self.cerrar_signal.emit()

    @pyqtSlot()
    def aplicar(self):
        def run():
            total  = len(self._copiar) + len(self._borrar)
            actual = 0
            for rel in self._copiar:
                actual += 1
                pct = actual / total * 100 if total else 100
                self.progreso_signal.emit(pct, os.path.basename(rel))
                try:
                    src = os.path.join(get_biblioteca(), rel)
                    dst = os.path.join(get_pd(), rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    print(f"[PD] Copiado: {rel}")
                except Exception as e:
                    print(f"[ERROR] {rel}: {e}")
            for rel in self._borrar:
                actual += 1
                pct = actual / total * 100 if total else 100
                self.progreso_signal.emit(pct, os.path.basename(rel))
                try:
                    dst = os.path.join(get_pd(), rel)
                    if os.path.isfile(dst): os.remove(dst)
                    _limpiar_carpetas_vacias(os.path.dirname(dst))
                    print(f"[PD] Borrado: {rel}")
                except Exception as e:
                    print(f"[ERROR] {rel}: {e}")
            self.progreso_signal.emit(100, "Completado!")
            time.sleep(0.8)
            self.cerrar_signal.emit()
        threading.Thread(target=run, daemon=True).start()


def abrir_popup_sync(copiar, borrar):
    api  = APISync(copiar, borrar)
    view = crear_ventana(520, 560, api)

    def on_progreso(pct, nombre):
        safe = nombre.replace("'", "").replace("\\", "\\\\")
        view.page().runJavaScript(
            f"if(typeof actualizarProgreso==='function') actualizarProgreso({pct:.1f},'{safe}');"
        )

    api.cerrar_signal.connect(view.close)
    api.progreso_signal.connect(on_progreso)
    view.load(QUrl.fromLocalFile(HTML_SYNC))
    view.show()
    view._keep = api


# ──────────────────────────────────────────────
#  POPUP SETTINGS
# ──────────────────────────────────────────────
class APISettings(QObject):
    cerrar_signal = pyqtSignal()

    @pyqtSlot(result=str)
    def getConfig(self):
        return json.dumps({
            "descargas":  get_descargas(),
            "biblioteca": get_biblioteca(),
            "pd":         get_pd()
        })

    @pyqtSlot(str)
    def guardar(self, json_str):
        global _config
        nueva = json.loads(json_str)
        _config["carpeta_descargas"]  = nueva.get("descargas",  get_descargas())
        _config["carpeta_biblioteca"] = nueva.get("biblioteca", get_biblioteca())
        _config["carpeta_pd"]         = nueva.get("pd",         get_pd())
        guardar_config(_config)
        print(f"[CONFIG] Guardada: {_config}")
        self.cerrar_signal.emit()

    @pyqtSlot()
    def cancelar(self):
        self.cerrar_signal.emit()

    @pyqtSlot(str, result=str)
    def elegirCarpeta(self, titulo):
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        carpeta = QFileDialog.getExistingDirectory(None, titulo, os.path.expanduser("~"))
        return carpeta or ""


def abrir_popup_settings(callback=None):
    api  = APISettings()
    view = crear_ventana(600, 500, api, frameless=True)

    def on_cerrar():
        view.close()
        if callback:
            callback()

    api.cerrar_signal.connect(on_cerrar)
    view.load(QUrl.fromLocalFile(HTML_SETTINGS))
    view.show()
    view._keep = api


# ──────────────────────────────────────────────
#  COLA DE TAREAS → hilo principal
# ──────────────────────────────────────────────
_cola = []
_cola_lock = threading.Lock()

def encolar(fn):
    with _cola_lock:
        _cola.append(fn)

def procesar_cola():
    with _cola_lock:
        tareas = _cola[:]
        _cola.clear()
    for fn in tareas:
        fn()

# ──────────────────────────────────────────────
#  PROCESAR ARCHIVO NUEVO
# ──────────────────────────────────────────────
def procesar_archivo_nuevo(path):
    nombre = os.path.basename(path)

    # No es audio → se queda en Downloads, no se toca
    if not es_audio(path):
        print(f"[IGNORADO] No es audio: {nombre}")
        return

    print(f"[NUEVO] Audio detectado: {nombre}")
    if not esperar_archivo_completo(path):
        print(f"[ERROR] Descarga no completada: {nombre}")
        return

    resultado = [None]
    done = threading.Event()

    def mostrar():
        def callback(carpeta):
            resultado[0] = carpeta
            done.set()
        abrir_popup_carpeta(nombre, callback)

    encolar(mostrar)
    done.wait()

    carpeta = resultado[0]
    if carpeta is None:
        print(f"[CANCELADO] {nombre}")
        return

    if carpeta in ("/ Raíz", "/ Raiz"):
        destino_local = os.path.join(get_biblioteca(), nombre)
        rel           = nombre
    else:
        destino_local = os.path.join(get_biblioteca(), carpeta, nombre)
        rel           = os.path.join(carpeta, nombre)

    if os.path.abspath(path) != os.path.abspath(destino_local):
        os.makedirs(os.path.dirname(destino_local), exist_ok=True)
        shutil.move(path, destino_local)
        print(f"[LOCAL] Movido a: {rel}")

    if pd_conectado():
        try:
            pd_copy(rel)
        except Exception as e:
            print(f"[ERROR] Copiando al PD: {e}")


# ──────────────────────────────────────────────
#  WATCHER — escucha DESCARGAS
# ──────────────────────────────────────────────
IGNORAR_EXT = {'.tmp', '.crdownload', '.part', '.download'}

_archivos_en_proceso = set()
_proceso_lock = threading.Lock()

def es_ignorable(path):
    return os.path.splitext(path)[1].lower() in IGNORAR_EXT

class ManejadorDescargas(FileSystemEventHandler):
    """Vigila la carpeta de descargas y filtra solo audio."""

    def on_created(self, event):
        if event.is_directory or es_ignorable(event.src_path):
            return
        with _proceso_lock:
            if event.src_path in _archivos_en_proceso: return
            _archivos_en_proceso.add(event.src_path)
        threading.Thread(target=self._procesar, args=(event.src_path,), daemon=True).start()

    def _procesar(self, path):
        try:
            procesar_archivo_nuevo(path)
        finally:
            with _proceso_lock:
                _archivos_en_proceso.discard(path)

    def on_moved(self, event):
        # Chrome/Soulseek renombra .crdownload → .mp3 al terminar
        if not event.is_directory and es_audio(event.dest_path):
            src_ext = os.path.splitext(event.src_path)[1].lower()
            if src_ext in IGNORAR_EXT or not es_audio(event.src_path):
                threading.Thread(target=procesar_archivo_nuevo, args=(event.dest_path,), daemon=True).start()


class ManejadorBiblioteca(FileSystemEventHandler):
    """Vigila LA CASA para replicar cambios al PD."""

    def on_deleted(self, event):
        if es_ignorable(event.src_path): return
        if pd_conectado(): pd_delete(relativo(event.src_path))

    def on_moved(self, event):
        if es_ignorable(event.src_path): return
        if not pd_conectado(): return
        rel_src = relativo(event.src_path)
        rel_dst = relativo(event.dest_path)
        if event.is_directory: pd_rename_dir(rel_src, rel_dst)
        else: pd_move(rel_src, rel_dst)


# ──────────────────────────────────────────────
#  MONITOR PENDRIVE
# ──────────────────────────────────────────────
_sync_lock = threading.Lock()

def hacer_sync():
    with _sync_lock:
        print("[PD] Calculando diff...")
        copiar, borrar = calcular_diff()
        print(f"[PD] Diff: {len(copiar)} copiar, {len(borrar)} borrar")
        if copiar or borrar:
            encolar(lambda c=copiar, b=borrar: abrir_popup_sync(c, b))
        else:
            print("[PD] TODO EN ORDEN.")

def monitor_pendrive():
    estaba = pd_conectado()
    if estaba:
        threading.Thread(target=hacer_sync, daemon=True).start()
    while True:
        time.sleep(CHECK_PD_CADA)
        ahora = pd_conectado()
        if ahora and not estaba:
            print("[PD] Pendrive detectado.")
            threading.Thread(target=hacer_sync, daemon=True).start()
        estaba = ahora


# ──────────────────────────────────────────────
#  SYSTEM TRAY
# ──────────────────────────────────────────────
def crear_icono_tray():
    """Crea un ícono simple ámbar para el tray."""
    ico_path = os.path.join(BASE_DIR, "sounduct.ico")
    if os.path.exists(ico_path):
        return QIcon(ico_path)
    # Ícono generado si no hay archivo
    px = QPixmap(32, 32)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setBrush(QColor("#f59e0b"))
    p.setPen(QColor("#f59e0b"))
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(px)


def setup_tray(app, observer_dl, observer_bib):
    tray = QSystemTrayIcon(crear_icono_tray(), app)
    tray.setToolTip("Sounduct — activo")

    menu = QMenu()

    accion_estado = menu.addAction("● Sounduct activo")
    accion_estado.setEnabled(False)
    menu.addSeparator()

    accion_settings = menu.addAction("Configuración")
    accion_settings.triggered.connect(lambda: encolar(lambda: abrir_popup_settings()))

    menu.addSeparator()

    accion_salir = menu.addAction("Salir")
    def salir():
        observer_dl.stop()
        observer_bib.stop()
        tray.hide()
        app.quit()
    accion_salir.triggered.connect(salir)

    tray.setContextMenu(menu)
    tray.show()
    return tray


# ──────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(get_biblioteca(), exist_ok=True)

    print("=" * 52)
    print("  SOUNDUCT v1")
    print(f"  Descargas : {get_descargas()}")
    print(f"  Biblioteca: {get_biblioteca()}")
    print(f"  PD        : {get_pd()}  ({'CONECTADO' if pd_conectado() else 'NO conectado'})")
    print("  Ctrl+C para detener")
    print("=" * 52)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    timer = QTimer()
    timer.timeout.connect(procesar_cola)
    timer.start(100)

    # Watcher descargas
    manejador_dl  = ManejadorDescargas()
    observer_dl   = Observer()
    observer_dl.schedule(manejador_dl, get_descargas(), recursive=False)
    observer_dl.start()

    # Watcher biblioteca (para replicar delete/move al PD)
    manejador_bib = ManejadorBiblioteca()
    observer_bib  = Observer()
    observer_bib.schedule(manejador_bib, get_biblioteca(), recursive=True)
    observer_bib.start()

    threading.Thread(target=monitor_pendrive, daemon=True).start()

    # System tray
    tray = setup_tray(app, observer_dl, observer_bib)

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        observer_dl.stop()
        observer_bib.stop()
        print("\n[SOUNDUCT] Detenido.")
    observer_dl.join()
    observer_bib.join()
