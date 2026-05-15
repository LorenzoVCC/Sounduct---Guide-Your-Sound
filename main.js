const { app, BrowserWindow, ipcMain, Tray, Menu, dialog, nativeImage } = require('electron')
const path = require('path')
const fs = require('fs')
const os = require('os')
const chokidar = require('chokidar')

// ── CONFIG ────────────────────────────────────────────────────────────
const BASE_DIR = __dirname
const CONFIG_PATH = path.join(BASE_DIR, 'config.json')

const CONFIG_DEFAULT = {
  carpeta_descargas: path.join(os.homedir(), 'Downloads'),
  carpeta_biblioteca: 'C:\\Users\\Lorenzo\\Desktop\\LA CASA',
  carpeta_pd: 'E:\\'
}

function cargarConfig() {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))
      for (const [k, v] of Object.entries(CONFIG_DEFAULT)) {
        if (!(k in cfg)) cfg[k] = v
      }
      return cfg
    }
  } catch {}
  return { ...CONFIG_DEFAULT }
}

function guardarConfig(cfg) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), 'utf8')
}

let _config = cargarConfig()
const getDescargas  = () => _config.carpeta_descargas
const getBiblioteca = () => _config.carpeta_biblioteca
const getPd         = () => _config.carpeta_pd

// ── CONSTANTES ────────────────────────────────────────────────────────
const AUDIO_FORMATOS = new Set(['.mp3', '.wav', '.aiff', '.flac', '.ogg', '.m4a'])
const IGNORAR_EXT   = new Set(['.tmp', '.crdownload', '.part', '.download'])
const CHECK_PD_CADA = 10_000

// ── HELPERS ───────────────────────────────────────────────────────────
const pdConectado = () => fs.existsSync(getPd())
const esAudio     = (p) => AUDIO_FORMATOS.has(path.extname(p).toLowerCase())
const esIgnorable = (p) => IGNORAR_EXT.has(path.extname(p).toLowerCase())
const relativo    = (p) => path.relative(getBiblioteca(), p)
const sleep       = (ms) => new Promise(r => setTimeout(r, ms))

async function esperarArchivoCompleto(filePath, espera = 3000, intentos = 60) {
  let tamanoAnterior = -1
  for (let i = 0; i < intentos; i++) {
    try {
      const { size } = await fs.promises.stat(filePath)
      if (size === tamanoAnterior && size > 0) return true
      tamanoAnterior = size
    } catch {
      return false
    }
    await sleep(espera)
  }
  return false
}

function listarCarpetas() {
  const carpetas = ['/ Raíz']
  try {
    const entries = fs.readdirSync(getBiblioteca(), { withFileTypes: true })
    entries
      .filter(e => e.isDirectory() && !e.name.startsWith('.'))
      .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()))
      .forEach(e => carpetas.push(e.name))
  } catch (e) {
    console.error('[ERROR] Listando carpetas:', e.message)
  }
  return carpetas
}

// ── DIFF ──────────────────────────────────────────────────────────────
function calcularDiff() {
  const casa = {}
  function walkCasa(dir) {
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name)
        if (e.isDirectory()) walkCasa(full)
        else try { casa[path.relative(getBiblioteca(), full)] = fs.statSync(full).size } catch {}
      }
    } catch {}
  }
  walkCasa(getBiblioteca())

  const pdFiles = {}
  function walkPd(dir) {
    try {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name === 'System Volume Information') continue
        const full = path.join(dir, e.name)
        if (e.isDirectory()) walkPd(full)
        else try { pdFiles[path.relative(getPd(), full)] = fs.statSync(full).size } catch {}
      }
    } catch {}
  }
  walkPd(getPd())

  const copiar = []
  const borrar = []
  for (const [rel, size] of Object.entries(casa)) {
    if (!(rel in pdFiles) || pdFiles[rel] !== size) copiar.push(rel)
  }
  for (const rel of Object.keys(pdFiles)) {
    if (!(rel in casa)) borrar.push(rel)
  }
  return { copiar, borrar }
}

function limpiarCarpetasVacias(dirPath) {
  while (true) {
    try {
      if (fs.existsSync(dirPath) && fs.statSync(dirPath).isDirectory()) {
        if (fs.readdirSync(dirPath).length === 0) {
          if (path.resolve(dirPath) === path.resolve(getPd())) break
          fs.rmdirSync(dirPath)
          dirPath = path.dirname(dirPath)
        } else break
      } else break
    } catch { break }
  }
}

async function pdCopy(rel) {
  const src = path.join(getBiblioteca(), rel)
  const dst = path.join(getPd(), rel)
  await fs.promises.mkdir(path.dirname(dst), { recursive: true })
  await fs.promises.copyFile(src, dst)
  const stat = fs.statSync(src)
  fs.utimesSync(dst, stat.atime, stat.mtime)
  console.log('[PD] Copiado:', rel)
}

async function pdDelete(rel) {
  const dst = path.join(getPd(), rel)
  try {
    const stat = await fs.promises.stat(dst)
    if (stat.isDirectory()) await fs.promises.rm(dst, { recursive: true })
    else await fs.promises.unlink(dst)
    limpiarCarpetasVacias(path.dirname(dst))
  } catch {}
}

async function pdMove(relSrc, relDst) {
  const src = path.join(getPd(), relSrc)
  const dst = path.join(getPd(), relDst)
  try {
    if ((await fs.promises.stat(src)).isFile()) {
      await fs.promises.mkdir(path.dirname(dst), { recursive: true })
      await fs.promises.rename(src, dst)
      limpiarCarpetasVacias(path.dirname(src))
    }
  } catch {}
}

// ── VENTANAS ──────────────────────────────────────────────────────────
function crearVentana(htmlFile, ancho, alto, frameless = true) {
  const win = new BrowserWindow({
    width: ancho,
    height: alto,
    frame: !frameless,
    resizable: false,
    alwaysOnTop: true,
    center: true,
    webPreferences: {
      preload: path.join(BASE_DIR, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  win.loadFile(htmlFile)
  return win
}

// ── POPUP CARPETA ─────────────────────────────────────────────────────
let _carpetaWin     = null
let _carpetaResolve = null
let _carpetaNombre  = ''

function resolverCarpeta(resultado) {
  if (_carpetaResolve) {
    const r = _carpetaResolve
    _carpetaResolve = null
    r(resultado)
  }
  if (_carpetaWin && !_carpetaWin.isDestroyed()) {
    const w = _carpetaWin
    _carpetaWin = null
    w.destroy()
  }
}

function abrirPopupCarpeta(nombre) {
  return new Promise(resolve => {
    _carpetaNombre  = nombre
    _carpetaResolve = resolve
    _carpetaWin     = crearVentana(path.join(BASE_DIR, 'popup_carpeta.html'), 650, 645)
    _carpetaWin.on('closed', () => {
      _carpetaWin = null
      resolverCarpeta(null)
    })
  })
}

ipcMain.handle('carpeta:get-nombre',  () => _carpetaNombre)
ipcMain.handle('carpeta:get-carpetas', () => listarCarpetas())
ipcMain.handle('carpeta:confirmar', (e, carpeta) => resolverCarpeta(carpeta))
ipcMain.handle('carpeta:cancelar',  () => resolverCarpeta(null))

// ── POPUP SYNC ────────────────────────────────────────────────────────
let _syncWin  = null
let _syncData = { copiar: [], borrar: [] }

function abrirPopupSync(copiar, borrar) {
  _syncData = { copiar, borrar }
  _syncWin  = crearVentana(path.join(BASE_DIR, 'popup_sync.html'), 520, 560)
  _syncWin.on('closed', () => { _syncWin = null })
}

async function ejecutarSync() {
  const { copiar, borrar } = _syncData
  const total = copiar.length + borrar.length
  let actual  = 0

  const enviarProgreso = (pct, nombre) => {
    if (_syncWin && !_syncWin.isDestroyed())
      _syncWin.webContents.send('sync:progreso', { pct, nombre })
  }

  for (const rel of copiar) {
    enviarProgreso(++actual / total * 100, path.basename(rel))
    try { await pdCopy(rel) } catch (e) { console.error('[ERROR]', rel, e.message) }
  }
  for (const rel of borrar) {
    enviarProgreso(++actual / total * 100, path.basename(rel))
    try { await pdDelete(rel) } catch (e) { console.error('[ERROR]', rel, e.message) }
  }

  enviarProgreso(100, 'Completado!')
  await sleep(800)
  if (_syncWin && !_syncWin.isDestroyed()) { _syncWin.destroy(); _syncWin = null }
}

ipcMain.handle('sync:get-datos', () => ({
  copiar: _syncData.copiar.length,
  borrar: _syncData.borrar.length,
  lista_borrar: _syncData.borrar
}))
ipcMain.handle('sync:ahora-no', () => { _syncWin?.destroy(); _syncWin = null })
ipcMain.handle('sync:aplicar', () => { ejecutarSync(); return null })

// ── POPUP SETTINGS ────────────────────────────────────────────────────
let _settingsWin = null

function abrirPopupSettings() {
  if (_settingsWin && !_settingsWin.isDestroyed()) { _settingsWin.focus(); return }
  _settingsWin = crearVentana(path.join(BASE_DIR, 'popup_settings.html'), 600, 500)
  _settingsWin.on('closed', () => { _settingsWin = null })
}

ipcMain.handle('settings:get-config', () => ({
  descargas:  getDescargas(),
  biblioteca: getBiblioteca(),
  pd:         getPd()
}))

ipcMain.handle('settings:guardar', (e, nueva) => {
  _config.carpeta_descargas  = nueva.descargas  ?? getDescargas()
  _config.carpeta_biblioteca = nueva.biblioteca ?? getBiblioteca()
  _config.carpeta_pd         = nueva.pd         ?? getPd()
  guardarConfig(_config)
  console.log('[CONFIG] Guardada:', _config)
  reiniciarWatchers()
  _settingsWin?.destroy()
  _settingsWin = null
})

ipcMain.handle('settings:cancelar', () => { _settingsWin?.destroy(); _settingsWin = null })

ipcMain.handle('settings:elegir-carpeta', async (e, titulo) => {
  const result = await dialog.showOpenDialog(_settingsWin, {
    title: titulo,
    properties: ['openDirectory']
  })
  return result.canceled ? '' : result.filePaths[0]
})

// ── COLA DE ARCHIVOS ──────────────────────────────────────────────────
// Serializa los popups de carpeta para que no se superpongan
let _cola = Promise.resolve()

function encolarArchivo(filePath) {
  _cola = _cola.then(() => procesarArchivoNuevo(filePath)).catch(() => {})
}

async function procesarArchivoNuevo(filePath) {
  const nombre = path.basename(filePath)
  if (!esAudio(filePath)) { console.log('[IGNORADO] No es audio:', nombre); return }

  console.log('[NUEVO] Audio detectado:', nombre)
  const ok = await esperarArchivoCompleto(filePath)
  if (!ok) { console.log('[ERROR] Descarga no completada:', nombre); return }

  const carpeta = await abrirPopupCarpeta(nombre)
  if (!carpeta) { console.log('[CANCELADO]', nombre); return }

  let destinoLocal, rel
  if (carpeta === '/ Raíz' || carpeta === '/ Raiz') {
    destinoLocal = path.join(getBiblioteca(), nombre)
    rel          = nombre
  } else {
    destinoLocal = path.join(getBiblioteca(), carpeta, nombre)
    rel          = path.join(carpeta, nombre)
  }

  if (path.resolve(filePath) !== path.resolve(destinoLocal)) {
    await fs.promises.mkdir(path.dirname(destinoLocal), { recursive: true })
    await fs.promises.rename(filePath, destinoLocal)
    console.log('[LOCAL] Movido a:', rel)
  }

  if (pdConectado()) {
    try { await pdCopy(rel) } catch (e) { console.error('[ERROR] Copiando al PD:', e.message) }
  }
}

// ── WATCHERS ──────────────────────────────────────────────────────────
let _watcherDl  = null
let _watcherBib = null

function iniciarWatchers() {
  fs.mkdirSync(getDescargas(),  { recursive: true })
  fs.mkdirSync(getBiblioteca(), { recursive: true })

  _watcherDl = chokidar.watch(getDescargas(), {
    depth: 0,
    ignoreInitial: true,
    persistent: true
  })
  _watcherDl.on('add', filePath => {
    if (!esIgnorable(filePath)) encolarArchivo(filePath)
  })

  _watcherBib = chokidar.watch(getBiblioteca(), {
    ignoreInitial: true,
    depth: 99,
    persistent: true
  })
  _watcherBib.on('unlink',    filePath => { if (!esIgnorable(filePath) && pdConectado()) pdDelete(relativo(filePath)) })
  _watcherBib.on('unlinkDir', dirPath  => { if (pdConectado()) pdDelete(relativo(dirPath)) })
  _watcherBib.on('rename',    (src, dst) => { if (!esIgnorable(src) && pdConectado()) pdMove(relativo(src), relativo(dst)) })
}

function reiniciarWatchers() {
  _watcherDl?.close()
  _watcherBib?.close()
  iniciarWatchers()
}

// ── MONITOR PENDRIVE ──────────────────────────────────────────────────
let _syncEnCurso = false

async function hacerSync() {
  if (_syncEnCurso) return
  _syncEnCurso = true
  try {
    console.log('[PD] Calculando diff...')
    const { copiar, borrar } = calcularDiff()
    console.log(`[PD] Diff: ${copiar.length} copiar, ${borrar.length} borrar`)
    if (copiar.length || borrar.length) abrirPopupSync(copiar, borrar)
    else console.log('[PD] TODO EN ORDEN.')
  } finally {
    _syncEnCurso = false
  }
}

function monitorPendrive() {
  let estabaConectado = pdConectado()
  if (estabaConectado) hacerSync()
  setInterval(() => {
    const ahora = pdConectado()
    if (ahora && !estabaConectado) { console.log('[PD] Pendrive detectado.'); hacerSync() }
    estabaConectado = ahora
  }, CHECK_PD_CADA)
}

// ── SYSTEM TRAY ───────────────────────────────────────────────────────
function crearTray() {
  const icoPath = path.join(BASE_DIR, 'assets', 'icons', 'sounduct-desktop-logo.ico')
  const icon    = fs.existsSync(icoPath)
    ? nativeImage.createFromPath(icoPath)
    : nativeImage.createEmpty()

  const tray = new Tray(icon)
  tray.setToolTip('Sounduct — activo')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '● Sounduct activo', enabled: false },
    { type: 'separator' },
    { label: 'Configuración', click: () => abrirPopupSettings() },
    { type: 'separator' },
    { label: 'Salir', click: () => app.quit() }
  ]))
  return tray
}

// ── MAIN ──────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  console.log('='.repeat(52))
  console.log('  SOUNDUCT v1 (Electron)')
  console.log(`  Descargas : ${getDescargas()}`)
  console.log(`  Biblioteca: ${getBiblioteca()}`)
  console.log(`  PD        : ${getPd()}  (${pdConectado() ? 'CONECTADO' : 'NO conectado'})`)
  console.log('='.repeat(52))

  iniciarWatchers()
  monitorPendrive()
  crearTray()
})

// Evitar que la app se cierre al cerrar todos los popups
app.on('window-all-closed', () => {})
