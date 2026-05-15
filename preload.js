const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  carpeta: {
    getNombre:  ()        => ipcRenderer.invoke('carpeta:get-nombre'),
    getCarpetas: ()       => ipcRenderer.invoke('carpeta:get-carpetas'),
    confirmar:  (carpeta) => ipcRenderer.invoke('carpeta:confirmar', carpeta),
    cancelar:   ()        => ipcRenderer.invoke('carpeta:cancelar')
  },
  sync: {
    getDatos:   ()   => ipcRenderer.invoke('sync:get-datos'),
    ahoraNno:   ()   => ipcRenderer.invoke('sync:ahora-no'),
    aplicar:    ()   => ipcRenderer.invoke('sync:aplicar'),
    onProgreso: (cb) => ipcRenderer.on('sync:progreso', (e, data) => cb(data))
  },
  settings: {
    getConfig:     ()        => ipcRenderer.invoke('settings:get-config'),
    guardar:       (cfg)     => ipcRenderer.invoke('settings:guardar', cfg),
    cancelar:      ()        => ipcRenderer.invoke('settings:cancelar'),
    elegirCarpeta: (titulo)  => ipcRenderer.invoke('settings:elegir-carpeta', titulo)
  }
})
