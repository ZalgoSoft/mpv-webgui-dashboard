#!/usr/bin/env python3
import json
import socket
import threading
import time
#from http.server import HTTPServer, BaseHTTPRequestListener
from http.server import HTTPServer, BaseHTTPRequestHandler

from urllib.parse import parse_qs, urlparse
import os

SOCKET_PATH = "/tmp/mpv-web-socket"
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>MPV Property Inspector</title>
    <meta charset="utf-8">
    <style>
/* Основные стили */
* {
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Arial', sans-serif;
    margin: 0;
    padding: 20px;
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    color: #e0e0e0;
    min-height: 100vh;
}

/* Контролы */
#controls {
    position: sticky;
    top: 0;
    background: rgba(30, 30, 30, 0.95);
    backdrop-filter: blur(10px);
    padding: 15px 20px;
    z-index: 1000;
    border-radius: 12px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    border: 1px solid #444;
}

button {
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    background: linear-gradient(135deg, #5a9e5a 0%, #4CAF50 100%);
    color: white;
    border: none;
    border-radius: 8px;
    transition: all 0.2s ease;
    box-shadow: 0 2px 8px rgba(76, 175, 80, 0.2);
}

button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
    background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
}

button:active {
    transform: translateY(0);
}

.search-input {
    flex: 1;
    min-width: 250px;
    padding: 10px 16px;
    font-size: 14px;
    background: #333;
    border: 1px solid #555;
    border-radius: 8px;
    color: #fff;
    transition: all 0.2s ease;
}

.search-input:focus {
    outline: none;
    border-color: #4CAF50;
    box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
    background: #3a3a3a;
}

.search-input::placeholder {
    color: #999;
}

/* Статус */
#status {
    margin: 15px 0;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    background: #2a2a2a;
    border-left: 4px solid #4CAF50;
}

.loading {
    color: #ffaa00;
    animation: pulse 1.5s ease-in-out infinite;
}

.error {
    color: #ff5555;
}

.success {
    color: #55ff55;
}

/* Группы */
.group-container {
    margin: 25px 0;
    background: #2a2a2a;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    border: 1px solid #3a3a3a;
    transition: box-shadow 0.2s ease;
}

.group-container:hover {
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3);
}

.group-header {
    padding: 16px 20px;
    background: linear-gradient(135deg, #333 0%, #2d2d2d 100%);
    border-bottom: 2px solid #4CAF50;
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    gap: 12px;
    transition: background 0.2s ease;
}

.group-header:hover {
    background: linear-gradient(135deg, #383838 0%, #333 100%);
}

.group-header.collapsed {
    border-bottom-color: #555;
}

.group-title {
    font-size: 18px;
    font-weight: 600;
    color: #fff;
    letter-spacing: 0.3px;
}

.group-count {
    background: #4CAF50;
    color: white;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
}

/* Сетка свойств */
.properties-grid {
    padding: 5px 0;
}

.property-row {
    display: grid;
    grid-template-columns: 250px 1fr;
    border-bottom: 1px solid #3a3a3a;
    transition: background 0.15s ease;
    animation: fadeIn 0.3s ease;
}

.property-row:hover {
    background: #323232;
}

.property-row:last-child {
    border-bottom: none;
}

.property-name {
    padding: 12px 16px;
    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: 13px;
    color: #6ed4c0;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    border-right: 1px solid #3a3a3a;
    word-break: break-word;
}

.property-name:hover {
    background: #3a3a3a;
    color: #8ee4d0;
    padding-left: 20px;
}

.property-value {
    padding: 8px 16px;
    font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
    font-size: 13px;
    word-break: break-word;
    display: flex;
    align-items: center;
    min-height: 45px;
}

/* Вложенные структуры */
.object-container,
.array-container {
    width: 100%;
}

.object-header,
.array-header {
    padding: 8px 12px;
    background: #333;
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    font-size: 12px;
    color: #aaa;
    transition: all 0.15s ease;
    border: 1px solid #444;
    margin-bottom: 4px;
}

.object-header:hover,
.array-header:hover {
    background: #3a3a3a;
    color: #fff;
    border-color: #4CAF50;
}

.toggle-icon {
    display: inline-block;
    width: 16px;
    margin-right: 4px;
    color: #4CAF50;
    transition: transform 0.2s ease;
}

.nested-content {
    margin-left: 16px;
    padding-left: 12px;
    border-left: 2px solid #4CAF50;
    display: block;
    animation: slideDown 0.2s ease;
}

.array-item {
    display: flex;
    align-items: flex-start;
    margin: 6px 0;
    padding: 4px 0;
}

.array-index {
    min-width: 40px;
    color: #888;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 8px 4px 0;
}

.array-value {
    flex: 1;
}

.object-property {
    display: flex;
    align-items: flex-start;
    margin: 6px 0;
    padding: 4px 0;
}

.object-key {
    min-width: 120px;
    color: #6ed4c0;
    font-weight: 500;
    padding: 4px 12px 4px 0;
}

.object-value {
    flex: 1;
}

/* Типы значений */
.null-value {
    color: #888;
    font-style: italic;
}

.boolean-value {
    font-weight: 600;
}

.boolean-value.true {
    color: #55cc55;
}

.boolean-value.false {
    color: #cc5555;
}

.number-value {
    color: #b5cea8;
}

.string-value {
    color: #ce9178;
}

.empty-array,
.empty-object {
    color: #888;
    font-style: italic;
}

/* Уведомления */
.notification {
    position: fixed;
    top: 20px;
    right: 20px;
    padding: 12px 20px;
    background: #333;
    color: white;
    border-radius: 8px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    z-index: 9999;
    opacity: 0;
    transform: translateX(400px);
    transition: all 0.3s ease;
    border-left: 4px solid #4CAF50;
}

.notification.show {
    opacity: 1;
    transform: translateX(0);
}

.notification.success {
    border-left-color: #4CAF50;
}

.notification.error {
    border-left-color: #f44336;
}

.notification.info {
    border-left-color: #2196F3;
}

/* Анимации */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-10px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes slideDown {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Скроллбар */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: #2a2a2a;
    border-radius: 5px;
}

::-webkit-scrollbar-thumb {
    background: #555;
    border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
    background: #666;
}

/* Адаптивность */
@media (max-width: 768px) {
    body {
        padding: 10px;
    }
    
    .property-row {
        grid-template-columns: 1fr;
    }
    
    .property-name {
        border-right: none;
        border-bottom: 1px solid #3a3a3a;
        background: #323232;
    }
    
    .object-property {
        flex-direction: column;
    }
    
    .object-key {
        min-width: auto;
        margin-bottom: 4px;
    }
    
    #controls {
        flex-direction: column;
        align-items: stretch;
    }
    
    .search-input {
        width: 100%;
    }
}
    </style>
</head>
<body>
    <div id="controls">
        <button onclick="getPropertyList()">📋 Get Property List</button>
        <button onclick="getAllProperties()">🔍 Get All Properties Values</button>
        <span id="status">Ready</span>
    </div>
    <div id="content">
        <div class="group-container">
            <div class="group-title">No data loaded</div>
            <p>Click "Get Property List" to load properties</p>
        </div>
    </div>
    <script>
let propertyGroups = {};
let propertyList = [];

async function apiCall(endpoint, body = null) {
    const options = {
        method: body ? 'POST' : 'GET',
        headers: body ? {'Content-Type': 'application/json'} : {}
    };
    if (body) options.body = JSON.stringify(body);
    
    try {
        const response = await fetch(endpoint, options);
        return await response.json();
    } catch (e) {
        console.error('API call failed:', e);
        return {error: e.message};
    }
}

async function getPropertyList() {
    document.getElementById('status').innerHTML = '<span class="loading">Loading property list...</span>';
    const result = await apiCall('/api/get_property_list');
    
    if (result.error && result.error !== 'success') {
        document.getElementById('status').innerHTML = `<span class="error">Error: ${result.error}</span>`;
        return;
    }
    
    propertyList = result.data || [];
    propertyGroups = groupProperties(propertyList);
    renderGroups();
    document.getElementById('status').innerHTML = `<span class="success">Loaded ${propertyList.length} properties</span>`;
}

function groupProperties(properties) {
    /*const groups = {
        'Playback': ['pause', 'speed', 'time-pos', 'duration', 'percent-pos', 'time-remaining', 'playback-time', 'eof-reached', 'seeking', 'core-idle'],
        'File & Stream': ['path', 'filename', 'media-title', 'file-size', 'file-format', 'stream-open-filename', 'stream-path', 'current-demuxer', 'demuxer-via-network', 'cache-speed', 'cache-buffering-state'],
        'Video': ['video-format', 'video-codec', 'video-params', 'width', 'height', 'dwidth', 'dheight', 'video-aspect-override', 'display-fps', 'estimated-vf-fps', 'container-fps', 'deinterlace-active', 'hwdec-current'],
        'Audio': ['volume', 'mute', 'audio-codec', 'audio-codec-name', 'audio-params', 'audio-device', 'aid', 'audio-delay', 'current-ao'],
        'Subtitles': ['sid', 'sub-delay', 'sub-speed', 'sub-pos', 'sub-text', 'sub-start', 'sub-end', 'secondary-sid', 'sub-visibility'],
        'Track Info': ['track-list', 'current-tracks', 'chapter', 'chapters', 'edition', 'editions', 'playlist', 'playlist-pos', 'playlist-count'],
        'Window & Display': ['fullscreen', 'window-scale', 'ontop', 'border', 'geometry', 'display-names', 'display-fps', 'focused', 'osd-width', 'osd-height'],
        'Options & Config': ['options', 'profile', 'config', 'config-dir', 'include', 'script-opts', 'watch-later-dir'],
        'MPV Info': ['mpv-version', 'ffmpeg-version', 'libass-version', 'platform', 'property-list', 'command-list', 'input-bindings']
    };*/
    const groups = {
    // Основное состояние воспроизведения
    'Playback State': ['pause', 'speed', 'pitch', 'time-pos', 'duration', 'percent-pos', 'time-remaining', 'playback-time', 'playtime-remaining', 'eof-reached', 'seeking', 'core-idle', 'idle-active', 'paused-for-cache', 'playback-abort', 'idle'],
    
    // Информация о файле и источнике
    'File & Source': ['path', 'filename', 'media-title', 'file-size', 'file-format', 'stream-open-filename', 'stream-path', 'current-demuxer', 'working-directory', 'stream-pos', 'stream-end', 'file-local-options'],
    
    // Видео параметры
    'Video Info': ['video-format', 'video-codec', 'video-params', 'video-out-params', 'video-dec-params', 'video-target-params', 'video-frame-info', 'width', 'height', 'dwidth', 'dheight', 'video-aspect-override', 'video-bitrate'],
    
    // Видео производительность
    'Video Performance': ['display-fps', 'container-fps', 'estimated-vf-fps', 'estimated-display-fps', 'vsync-ratio', 'vsync-jitter', 'mistimed-frame-count', 'frame-drop-count', 'decoder-frame-drop-count', 'vo-delayed-frame-count', 'estimated-frame-count', 'estimated-frame-number', 'perf-info'],
    
    // Аудио параметры
    'Audio Info': ['volume', 'mute', 'ao-volume', 'ao-mute', 'volume-gain', 'audio-codec', 'audio-codec-name', 'audio-params', 'audio-out-params', 'aid', 'audio-delay', 'audio-bitrate', 'mixer-active', 'current-ao'],
    
    // Аудио устройства
    'Audio Devices': ['audio-device', 'audio-device-list', 'audio-exclusive', 'audio-fallback-to-null', 'audio-stream-silence', 'audio-wait-open', 'audio-client-name', 'audio-buffer', 'audio-set-media-role'],
    
    // Субтитры основные
    'Subtitles Main': ['sid', 'sub-delay', 'sub-speed', 'sub-pos', 'sub-text', 'sub-start', 'sub-end', 'sub-visibility', 'secondary-sid', 'secondary-sub-delay', 'secondary-sub-pos', 'secondary-sub-text', 'secondary-sub-start', 'secondary-sub-end', 'secondary-sub-visibility'],
    
    // Субтитры ASS/SSA
    'Subtitles ASS': ['sub-ass', 'sub-ass-extradata', 'sub-text-ass', 'sub-ass-style-overrides', 'sub-ass-styles', 'sub-ass-hinting', 'sub-ass-shaper', 'sub-ass-justify', 'sub-ass-override', 'sub-ass-force-style', 'sub-ass-force-margins', 'sub-ass-use-video-data', 'sub-ass-video-aspect-override', 'sub-ass-vsfilter-color-compat', 'sub-ass-scale-with-window', 'sub-ass-prune-delay', 'secondary-sub-ass-override'],
    
    // Субтитры стили
    'Subtitles Style': ['sub-font', 'sub-font-size', 'sub-color', 'sub-outline-color', 'sub-back-color', 'sub-outline-size', 'sub-border-color', 'sub-shadow-color', 'sub-border-style', 'sub-border-size', 'sub-shadow-offset', 'sub-spacing', 'sub-margin-x', 'sub-margin-y', 'sub-align-x', 'sub-align-y', 'sub-blur', 'sub-bold', 'sub-italic', 'sub-justify', 'sub-scale', 'sub-scale-by-window', 'sub-scale-with-window', 'sub-line-spacing', 'sub-use-margins'],
    
    // Субтитры фильтры
    'Subtitles Filters': ['sub-filter-sdh', 'sub-filter-sdh-harder', 'sub-filter-sdh-enclosures', 'sub-filter-regex-enable', 'sub-filter-regex-plain', 'sub-filter-regex', 'sub-filter-jsre', 'sub-filter-regex-warn'],
    
    // Треки и главы
    'Tracks & Chapters': ['track-list', 'current-tracks', 'chapter', 'chapters', 'chapter-list', 'edition', 'editions', 'edition-list', 'chapter-metadata'],
    
    // Плейлист
    'Playlist': ['playlist', 'playlist-path', 'playlist-pos', 'playlist-pos-1', 'playlist-current-pos', 'playlist-playing-pos', 'playlist-count', 'playlist-start', 'shuffle', 'loop-playlist', 'loop-file', 'loop'],
    
    // Метаданные
    'Metadata': ['metadata', 'filtered-metadata', 'vf-metadata', 'af-metadata', 'media-title', 'title', 'force-media-title'],
    
    // Окно и геометрия
    'Window & Geometry': ['fullscreen', 'fs', 'window-scale', 'current-window-scale', 'ontop', 'ontop-level', 'border', 'title-bar', 'geometry', 'autofit', 'autofit-larger', 'autofit-smaller', 'auto-window-resize', 'window-minimized', 'window-maximized', 'window-id', 'wid', 'focused'],
    
    // Позиционирование окна
    'Window Position': ['screen', 'screen-name', 'fs-screen', 'fs-screen-name', 'monitoraspect', 'monitorpixelaspect', 'on-all-workspaces', 'force-window-position', 'force-window', 'snap-window', 'keepaspect', 'keepaspect-window'],
    
    // Дисплей и мониторы
    'Display Info': ['display-names', 'display-width', 'display-height', 'display-fps', 'display-hidpi-scale', 'hidpi-window-scale', 'display-sync-active'],
    
    // Видео фильтры и трансформации
    'Video Transform': ['video-zoom', 'video-pan-x', 'video-pan-y', 'video-align-x', 'video-align-y', 'video-scale-x', 'video-scale-y', 'video-crop', 'video-unscaled', 'video-recenter', 'panscan', 'video-rotate', 'deinterlace', 'deinterlace-active', 'deinterlace-field-parity'],
    
    // Видео margins
    'Video Margins': ['video-margin-ratio-left', 'video-margin-ratio-right', 'video-margin-ratio-top', 'video-margin-ratio-bottom'],
    
    // Цветокоррекция
    'Color Correction': ['brightness', 'saturation', 'contrast', 'hue', 'gamma', 'video-output-levels', 'colormatrix', 'colormatrix-input-range', 'colormatrix-primaries', 'colormatrix-gamma'],
    
    // HDR и tone mapping
    'HDR & Tone Mapping': ['target-prim', 'target-trc', 'target-peak', 'hdr-reference-white', 'tone-mapping', 'tone-mapping-param', 'inverse-tone-mapping', 'tone-mapping-max-boost', 'tone-mapping-visualize', 'gamut-mapping-mode', 'hdr-compute-peak', 'hdr-peak-percentile', 'hdr-peak-decay-rate', 'hdr-scene-threshold-low', 'hdr-scene-threshold-high', 'hdr-contrast-recovery', 'hdr-contrast-smoothness', 'target-contrast', 'target-gamut', 'sdr-adjust-gamma', 'treat-srgb-as-power22'],
    
    // Аппаратное декодирование
    'Hardware Decoding': ['hwdec', 'hwdec-current', 'hwdec-interop', 'hwdec-codecs', 'hwdec-extra-frames', 'hwdec-image-format', 'hwdec-software-fallback', 'hwdec-threads', 'gpu-hwdec-interop', 'vaapi-device', 'vd-lavc-dr'],
    
    // GPU и рендеринг
    'GPU & Rendering': ['gpu-context', 'gpu-api', 'current-gpu-context', 'gpu-debug', 'gpu-sw', 'gpu-dumb-mode', 'vulkan-device', 'vulkan-swap-mode', 'vulkan-queue-count', 'vulkan-async-transfer', 'vulkan-async-compute', 'vulkan-display-display', 'vulkan-display-mode', 'vulkan-display-plane', 'drm-device', 'drm-connector', 'drm-mode', 'drm-draw-plane', 'drm-format', 'drm-vrr-enabled', 'opengl-pbo', 'opengl-es', 'opengl-early-flush'],
    
    // Скалеры и фильтры
    'Scalers': ['scale', 'scale-param1', 'scale-param2', 'scale-blur', 'scale-taper', 'scale-clamp', 'scale-radius', 'scale-antiring', 'scale-window', 'dscale', 'cscale', 'tscale', 'scaler-resizes-only', 'correct-downscaling', 'linear-downscaling', 'linear-upscaling', 'sigmoid-upscaling', 'sigmoid-center', 'sigmoid-slope'],
    
    // Шейдеры и пост-обработка
    'Shaders & Post-processing': ['glsl-shaders', 'glsl-shader-opts', 'deband', 'deband-iterations', 'deband-threshold', 'deband-range', 'deband-grain', 'sharpen', 'gpu-tex-pad-x', 'gpu-tex-pad-y', 'gpu-shader-cache', 'gpu-shader-cache-dir', 'background', 'background-color', 'background-blur-radius', 'border-background', 'corner-rounding', 'blend-subtitles'],
    
    // Интерполяция
    'Interpolation': ['interpolation', 'interpolation-threshold', 'interpolation-preserve', 'video-sync', 'video-sync-max-video-change', 'video-sync-max-audio-change', 'video-sync-max-factor', 'video-timing-offset', 'autosync'],
    
    // ICC профили
    'ICC Profiles': ['use-embedded-icc-profile', 'icc-profile', 'icc-profile-auto', 'icc-cache', 'icc-cache-dir', 'icc-intent', 'icc-force-contrast', 'icc-3dlut-size', 'icc-use-luma'],
    
    // LUT
    'LUT': ['lut', 'lut-type', 'image-lut', 'image-lut-type', 'target-lut', 'target-colorspace-hint', 'target-colorspace-hint-mode', 'target-colorspace-hint-strict'],
    
    // Dithering
    'Dithering': ['dither', 'dither-depth', 'dither-size-fruit', 'temporal-dither', 'temporal-dither-period', 'error-diffusion', 'fbo-format'],
    
    // Видео выход (VO)
    'Video Output': ['vo', 'current-vo', 'vo-configured', 'vo-passes', 'display-swapchain', 'swapchain-depth'],
    
    // VO специфичные опции
    'VO Specific': ['xv-port', 'xv-adaptor', 'xv-ck', 'xv-ck-method', 'xv-colorkey', 'xv-buffers', 'vo-vaapi-scaling', 'vo-vaapi-scaled-osd', 'vo-null-fps', 'vo-tct-algo', 'vo-tct-width', 'vo-tct-height', 'vo-tct-256', 'vo-tct-buffering', 'vo-sixel-dither', 'vo-sixel-width', 'vo-sixel-height', 'vo-kitty-width', 'vo-kitty-height'],
    
    // Аудио выход (AO)
    'Audio Output': ['ao', 'current-ao', 'audio-exclusive', 'audio-fallback-to-null'],
    
    // PulseAudio
    'PulseAudio': ['pulse-host', 'pulse-buffer', 'pulse-latency-hacks', 'pulse-allow-suspended'],
    
    // ALSA
    'ALSA': ['alsa-resample', 'alsa-mixer-device', 'alsa-mixer-name', 'alsa-mixer-index', 'alsa-non-interleaved', 'alsa-ignore-chmap', 'alsa-buffer-time', 'alsa-periods'],
    
    // JACK
    'JACK': ['jack-port', 'jack-name', 'jack-autostart', 'jack-connect', 'jack-std-channel-layout'],
    
    // PipeWire
    'PipeWire': ['pipewire-buffer', 'pipewire-remote', 'pipewire-volume-mode'],
    
    // AO Null
    'AO Null': ['ao-null-untimed', 'ao-null-buffer', 'ao-null-outburst', 'ao-null-speed', 'ao-null-latency', 'ao-null-broken-eof', 'ao-null-broken-delay', 'ao-null-channel-layouts', 'ao-null-format'],
    
    // AO PCM
    'AO PCM': ['ao-pcm-file', 'ao-pcm-waveheader', 'ao-pcm-append'],
    
    // Демультиплексор
    'Demuxer': ['demuxer', 'current-demuxer', 'demuxer-via-network', 'demuxer-start-time', 'demuxer-cache-state', 'demuxer-cache-duration', 'demuxer-cache-time', 'demuxer-cache-idle', 'demuxer-thread', 'demuxer-readahead-secs', 'demuxer-hysteresis-secs', 'demuxer-max-bytes', 'demuxer-max-back-bytes', 'demuxer-donate-buffer', 'demuxer-seekable-cache', 'demuxer-backward-playback-step'],
    
    // Demuxer lavf
    'Demuxer lavf': ['demuxer-lavf-list', 'demuxer-lavf-probesize', 'demuxer-lavf-probe-info', 'demuxer-lavf-format', 'demuxer-lavf-analyzeduration', 'demuxer-lavf-buffersize', 'demuxer-lavf-allow-mimetype', 'demuxer-lavf-probescore', 'demuxer-lavf-hacks', 'demuxer-lavf-o', 'demuxer-lavf-linearize-timestamps', 'demuxer-lavf-propagate-opts'],
    
    // Demuxer raw
    'Demuxer Raw': ['demuxer-rawaudio-channels', 'demuxer-rawaudio-rate', 'demuxer-rawaudio-format', 'demuxer-rawvideo-w', 'demuxer-rawvideo-h', 'demuxer-rawvideo-format', 'demuxer-rawvideo-mp-format', 'demuxer-rawvideo-codec', 'demuxer-rawvideo-fps', 'demuxer-rawvideo-size'],
    
    // Demuxer mkv
    'Demuxer MKV': ['demuxer-mkv-subtitle-preroll', 'demuxer-mkv-subtitle-preroll-secs', 'demuxer-mkv-subtitle-preroll-secs-index', 'demuxer-mkv-probe-video-duration', 'demuxer-mkv-probe-start-time', 'demuxer-mkv-crop-compat'],
    
    // Кеширование
    'Cache': ['cache', 'cache-speed', 'cache-buffering-state', 'cache-pause', 'cache-pause-initial', 'cache-pause-wait', 'cache-secs', 'cache-on-disk', 'demuxer-cache-wait', 'demuxer-cache-dir', 'demuxer-cache-unlink-files'],
    
    // Декодеры видео
    'Video Decoder': ['vd', 'vd-lavc-fast', 'vd-lavc-film-grain', 'vd-lavc-show-all', 'vd-lavc-skiploopfilter', 'vd-lavc-skipidct', 'vd-lavc-skipframe', 'vd-lavc-framedrop', 'vd-lavc-threads', 'vd-lavc-bitexact', 'vd-lavc-assume-old-x264', 'vd-lavc-check-hw-profile', 'vd-lavc-o', 'vd-lavc-software-fallback', 'vd-apply-cropping'],
    
    // Декодеры аудио
    'Audio Decoder': ['ad', 'ad-lavc-ac3drc', 'ad-lavc-downmix', 'ad-lavc-threads', 'ad-lavc-o', 'audio-spdif'],
    
    // Очереди декодеров
    'Decoder Queues': ['vd-queue-enable', 'vd-queue-max-secs', 'vd-queue-max-bytes', 'vd-queue-max-samples', 'ad-queue-enable', 'ad-queue-max-secs', 'ad-queue-max-bytes', 'ad-queue-max-samples'],
    
    // OSD
    'OSD': ['osd-level', 'osd-width', 'osd-height', 'osd-par', 'osd-dimensions', 'osd-scale', 'osd-scale-by-window', 'video-osd', 'osd-bar', 'osd-on-seek', 'osd-duration', 'osd-fractions'],
    
    // OSD стили
    'OSD Style': ['osd-font', 'osd-font-size', 'osd-color', 'osd-outline-color', 'osd-back-color', 'osd-outline-size', 'osd-border-color', 'osd-shadow-color', 'osd-border-style', 'osd-border-size', 'osd-shadow-offset', 'osd-spacing', 'osd-margin-x', 'osd-margin-y', 'osd-align-x', 'osd-align-y', 'osd-blur', 'osd-bold', 'osd-italic', 'osd-justify', 'osd-font-provider', 'osd-fonts-dir', 'osd-shaper'],
    
    // OSD сообщения
    'OSD Messages': ['osd-playing-msg', 'osd-playing-msg-duration', 'osd-status-msg', 'osd-msg1', 'osd-msg2', 'osd-msg3', 'osd-playlist-entry'],
    
    // OSD bar
    'OSD Bar': ['osd-bar-align-x', 'osd-bar-align-y', 'osd-bar-w', 'osd-bar-h', 'osd-bar-outline-size', 'osd-bar-border-size', 'osd-bar-marker-scale', 'osd-bar-marker-min-size', 'osd-bar-marker-style'],
    
    // Терминал
    'Terminal': ['terminal', 'term-osd', 'term-osd-bar', 'term-osd-bar-chars', 'term-title', 'term-playing-msg', 'term-status-msg', 'term-size', 'term-clip-cc', 'quiet', 'really-quiet', 'msg-level', 'msg-color', 'msg-module', 'msg-time'],
    
    // Скриншоты
    'Screenshots': ['screenshot-template', 'screenshot-dir', 'screenshot-directory', 'screenshot-sw', 'screenshot-format', 'screenshot-jpeg-quality', 'screenshot-jpeg-source-chroma', 'screenshot-png-compression', 'screenshot-png-filter', 'screenshot-webp-lossless', 'screenshot-webp-quality', 'screenshot-webp-compression', 'screenshot-jxl-distance', 'screenshot-jxl-effort', 'screenshot-avif-encoder', 'screenshot-avif-opts', 'screenshot-avif-pixfmt', 'screenshot-high-bit-depth', 'screenshot-tag-colorspace'],
    
    // Ввод и управление
    'Input': ['input-conf', 'input-key-list', 'input-bindings', 'input-default-bindings', 'input-builtin-bindings', 'input-builtin-dragging', 'input-ar-delay', 'input-ar-rate', 'input-doubleclick-time', 'input-right-alt-gr', 'input-key-fifo-size', 'input-cursor', 'input-cursor-passthrough', 'input-vo-keyboard', 'input-media-keys', 'input-preprocess-wheel', 'input-ime', 'input-test'],
    
    // Мышь и тач
    'Mouse & Touch': ['mouse-pos', 'touch-pos', 'tablet-pos', 'input-touch-emulate-mouse', 'input-tablet-emulate-mouse', 'input-dragging-deadzone', 'window-dragging', 'cursor-autohide', 'cursor-autohide-fs-only', 'drag-and-drop', 'native-touch'],
    
    // Сеть и стриминг
    'Network & Streaming': ['demuxer-via-network', 'http-header-fields', 'user-agent', 'referrer', 'cookies', 'cookies-file', 'tls-verify', 'tls-ca-file', 'tls-cert-file', 'tls-key-file', 'network-timeout', 'http-proxy', 'rtsp-transport', 'hls-bitrate', 'stream-lavf-o', 'stream-record', 'stream-buffer-size', 'stream-dump'],
    
    // yt-dlp / youtube-dl
    'YouTube-DL': ['ytdl', 'ytdl-format', 'ytdl-raw-options'],
    
    // DVD/Blu-ray/CD
    'Optical Media': ['dvd-device', 'dvd-speed', 'dvd-angle', 'bluray-device', 'bluray-angle', 'cdda-device', 'cdda-speed', 'cdda-paranoia', 'cdda-sector-size', 'cdda-overlap', 'cdda-toc-offset', 'cdda-skip', 'cdda-span-a', 'cdda-span-b', 'cdda-cdtext'],
    
    // DVB
    'DVB': ['dvbin-prog', 'dvbin-card', 'dvbin-timeout', 'dvbin-file', 'dvbin-full-transponder', 'dvbin-channel-switch-offset'],
    
    // Loop и AB
    'Loop & AB': ['ab-loop-a', 'ab-loop-b', 'ab-loop-count', 'loop', 'loop-file', 'loop-playlist', 'remaining-file-loops', 'remaining-ab-loops'],
    
    // Seek
    'Seek': ['seekable', 'partially-seekable', 'hr-seek', 'hr-seek-demuxer-offset', 'hr-seek-framedrop', 'force-seekable'],
    
    // Главы
    'Chapters': ['chapter', 'chapters', 'chapter-list', 'ordered-chapters', 'ordered-chapters-files', 'chapter-merge-threshold', 'chapter-seek-threshold', 'chapters-file', 'merge-files'],
    
    // Watch Later и resume
    'Watch Later': ['watch-later-dir', 'watch-later-directory', 'watch-later-options', 'current-watch-later-dir', 'resume-playback', 'resume-playback-check-mtime', 'save-position-on-quit', 'write-filename-in-watch-later-config', 'ignore-path-in-watch-later-config', 'save-watch-history', 'watch-history-path'],
    
    // ReplayGain
    'ReplayGain': ['replaygain', 'replaygain-preamp', 'replaygain-clip', 'replaygain-fallback'],
    
    // Синхронизация
    'Sync': ['avsync', 'total-avsync-change', 'audio-pts', 'clock', 'audio-speed-correction', 'video-speed-correction', 'initial-audio-sync', 'correct-pts', 'framedrop', 'video-latency-hacks', 'untimed'],
    
    // Аудио ресемплинг
    'Audio Resample': ['audio-samplerate', 'audio-channels', 'audio-format', 'audio-pitch-correction', 'audio-normalize-downmix', 'audio-resample-filter-size', 'audio-resample-phase-shift', 'audio-resample-linear', 'audio-resample-cutoff', 'audio-resample-max-output-size', 'audio-swresample-o', 'gapless-audio'],
    
    // SWScale и zimg
    'SWScale & zimg': ['sws-scaler', 'sws-lgb', 'sws-cgb', 'sws-cvs', 'sws-chs', 'sws-ls', 'sws-cs', 'sws-fast', 'sws-bitexact', 'sws-allow-zimg', 'zimg-scaler', 'zimg-scaler-param-a', 'zimg-scaler-param-b', 'zimg-scaler-chroma', 'zimg-scaler-chroma-param-a', 'zimg-scaler-chroma-param-b', 'zimg-dither', 'zimg-fast', 'zimg-threads'],
    
    // Wayland
    'Wayland': ['wayland-app-id', 'wayland-configure-bounds', 'wayland-content-type', 'wayland-disable-vsync', 'wayland-internal-vsync', 'wayland-edge-pixels-pointer', 'wayland-edge-pixels-touch', 'wayland-present'],
    
    // X11
    'X11': ['x11-name', 'x11-netwm', 'x11-bypass-compositor', 'x11-present', 'x11-wid-title', 'stop-screensaver'],
    
    // Конфигурация и опции
    'Config': ['config', 'config-dir', 'include', 'profile', 'profile-list', 'options', 'option-info', 'script-opts', 'use-filedir-conf', 'reset-on-next-file', 'load-scripts'],
    
    // Скрипты
    'Scripts': ['scripts', 'load-scripts', 'osc', 'load-stats-overlay', 'load-console', 'load-osd-console', 'load-auto-profiles', 'load-select', 'load-positioning', 'load-commands', 'load-context-menu'],
    
    // Внешние файлы
    'External Files': ['sub-files', 'audio-files', 'cover-art-files', 'external-files', 'autoload-files', 'sub-file-paths', 'audio-file-paths'],
    
    // Автовыбор
    'Auto Selection': ['alang', 'slang', 'vlang', 'track-auto-selection', 'sub-auto', 'sub-auto-exts', 'audio-file-auto', 'audio-exts', 'audio-file-auto-exts', 'cover-art-auto', 'image-exts', 'cover-art-auto-exts', 'cover-art-whitelist', 'video-exts', 'archive-exts', 'playlist-exts', 'subs-with-matching-audio', 'subs-match-os-language', 'subs-fallback', 'subs-fallback-forced'],
    
    // Разное
    'Misc': ['pid', 'keep-open', 'keep-open-pause', 'image-display-duration', 'force-window', 'volume-max', 'volume-gain-max', 'volume-gain-min', 'mc', 'sstep', 'stop-playback-on-init-failure', 'directory-mode', 'directory-filter-types', 'index', 'mf-fps', 'mf-type', 'autocreate-playlist', 'rar-list-all-volumes', 'load-unsafe-playlists', 'access-references'],
    
    // Кодирование
    'Encoding': ['o', 'of', 'ofopts', 'ovc', 'ovcopts', 'oac', 'oacopts', 'orawts', 'ocopy-metadata', 'oset-metadata', 'oremove-metadata'],
    
    // Clipboard
    'Clipboard': ['clipboard', 'current-clipboard-backend', 'clipboard-monitor', 'clipboard-xwayland', 'clipboard-backends'],
    
    // Информация о MPV
    'MPV Info': ['mpv-version', 'mpv-configuration', 'ffmpeg-version', 'libass-version', 'platform', 'property-list', 'command-list', 'protocol-list', 'decoder-list', 'encoder-list', 'input-key-list', 'profile-list', 'input-bindings', 'menu-data', 'user-data'],
    
    // Устаревшие/алиасы
    'Deprecated/Aliases': ['fs', 'sstep', 'wid', 'ontop', 'playlist-pos-1', 'sub-forced-only-cur', 'audio-display', 'display-tags', 'sub-codepage', 'native-fs', 'native-keyrepeat', 'force-render', 'vo-image-outdir', 'vo-image-format', 'vo-image-jpeg-quality', 'vo-image-png-compression', 'vo-image-high-bit-depth', 'vo-image-tag-colorspace', 'override-display-fps', 'video', 'audio', 'sub', 'frames', 'start', 'end', 'length', 'play-dir', 'lavfi-complex', 'audio-demuxer', 'sub-demuxer', 'prefetch-playlist', 'sub-create-cc-track', 'video-backward-overlap', 'audio-backward-overlap', 'video-backward-batch', 'audio-backward-batch', 'metadata-codepage', 'gamma-factor', 'gamma-auto', 'opengl-glfinish', 'opengl-waitvsync', 'opengl-swapinterval', 'opengl-check-pattern-a', 'opengl-check-pattern-b', 'egl-config-id', 'egl-output-format', 'opengl-rectangle-textures', 'background-tile-color-0', 'background-tile-color-1', 'background-tile-size', 'libplacebo-opts', 'spirv-compiler', 'sub-hdr-peak', 'image-subs-hdr-peak', 'allow-delayed-peak-detect', 'drm-drmprime-video-plane', 'drm-draw-surface-size', 'vf', 'af', 'osd-sym-cc', 'osd-ass-cc', 'ambient-light', 'media-controls', 'dump-stats', 'log-file', 'display-tags', 'play-direction', 'rebase-start-time', 'force-seekable', 'demuxer-termination-timeout', 'stretch-dvd-subs', 'stretch-image-subs-to-screen', 'image-subs-video-resolution', 'sub-fix-timing', 'sub-fix-timing-threshold', 'sub-fix-timing-keep', 'sub-stretch-durations', 'sub-gauss', 'sub-gray', 'sub-scale-signs', 'sub-ass-line-spacing', 'sub-vsfilter-bidi-compat', 'embeddedfonts', 'sub-hinting', 'sub-shaper', 'sub-clear-on-seek', 'teletext-page', 'sub-past-video-end', 'sub-lavc-o', 'sub-glyph-limit', 'sub-bitmap-max-size', 'sub-font-provider', 'sub-fonts-dir', 'osd-selected-color', 'osd-selected-outline-color', 'force-rgba-osd-rendering', 'osd-prune-delay', 'osd-glyph-limit', 'osd-bitmap-max-size', 'osd-font-provider', 'osd-fonts-dir']
};
    
    const grouped = {};
    const assigned = new Set();
    
    for (const group of Object.keys(groups)) {
        grouped[group] = [];
    }
    grouped['Other'] = [];
    
    for (const prop of properties) {
        let found = false;
        for (const [group, props] of Object.entries(groups)) {
            if (props.includes(prop)) {
                grouped[group].push(prop);
                assigned.add(prop);
                found = true;
                break;
            }
        }
        if (!found) {
            grouped['Other'].push(prop);
        }
    }
    
    for (const group of Object.keys(grouped)) {
        grouped[group].sort();
    }
    
    return grouped;
}

// ========== РЕКУРСИВНАЯ ФУНКЦИЯ С DIV-СТРУКТУРОЙ ==========
function renderNestedDiv(data, depth = 0) {
    const id = `nested_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    // 1. Обработка null/undefined
    if (data === null || data === undefined) {
        return `<span class="null-value">null</span>`;
    }
    
    // 2. Обработка примитивов
    if (typeof data !== 'object') {
        if (typeof data === 'boolean') {
            return `<span class="boolean-value ${data}">${data ? '✓' : '✗'} ${data}</span>`;
        }
        if (typeof data === 'number') {
            const formatted = Number.isInteger(data) ? String(data) : data.toFixed(6).replace(/\\.?0+$/, '');
            return `<span class="number-value">${formatted}</span>`;
        }
        return `<span class="string-value">${String(data).replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>`;
    }
    
    // 3. Обработка массивов
    if (Array.isArray(data)) {
        if (data.length === 0) {
            return `<span class="empty-array">[ ]</span>`;
        }
        
        let html = `<div class="array-container">`;
        html += `<div class="array-header" onclick="toggleNested('${id}')">`;
        html += `<span class="toggle-icon">▼</span> Array [${data.length}]`;
        html += `</div>`;
        html += `<div id="${id}" class="nested-content">`;
        
        data.forEach((item, index) => {
            html += `<div class="array-item">`;
            html += `<span class="array-index">[${index}]</span>`;
            html += `<div class="array-value">${renderNestedDiv(item, depth + 1)}</div>`;
            html += `</div>`;
        });
        
        html += `</div></div>`;
        return html;
    }
    
    // 4. Обработка объектов
    if (Object.keys(data).length === 0) {
        return `<span class="empty-object">{ }</span>`;
    }
    
    let html = `<div class="object-container">`;
    html += `<div class="object-header" onclick="toggleNested('${id}')">`;
    html += `<span class="toggle-icon">▼</span> Object {${Object.keys(data).length}}`;
    html += `</div>`;
    html += `<div id="${id}" class="nested-content">`;
    
    const keys = Object.keys(data).sort();
    for (const key of keys) {
        html += `<div class="object-property">`;
        html += `<span class="object-key">${key}:</span>`;
        html += `<div class="object-value">${renderNestedDiv(data[key], depth + 1)}</div>`;
        html += `</div>`;
    }
    
    html += `</div></div>`;
    return html;
}

// ========== ФУНКЦИЯ ДЛЯ РАСКРЫТИЯ/СКРЫТИЯ ==========
function toggleNested(id) {
    const element = document.getElementById(id);
    const header = element.previousElementSibling;
    const icon = header.querySelector('.toggle-icon');
    
    if (element.style.display === 'none') {
        element.style.display = 'block';
        icon.textContent = '▼';
    } else {
        element.style.display = 'none';
        icon.textContent = '▶';
    }
}

// ========== КОПИРОВАНИЕ ЗНАЧЕНИЯ В БУФЕР ==========
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showNotification('Copied to clipboard!', 'success');
    } catch (err) {
        showNotification('Failed to copy', 'error');
    }
}

// ========== ПОКАЗ УВЕДОМЛЕНИЙ ==========
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 2000);
    }, 10);
}

// ========== ОТРИСОВКА ГРУПП ==========
function renderGroups() {
    const container = document.getElementById('content');
    let html = '';
    
    for (const [groupName, props] of Object.entries(propertyGroups)) {
        if (props.length === 0) continue;
        
        html += `<div class="group-container">`;
        html += `<div class="group-header">`;
        html += `<span class="group-title">${groupName}</span>`;
        html += `<span class="group-count">${props.length}</span>`;
        html += `</div>`;
        html += `<div class="properties-grid">`;
        
        for (const prop of props) {
            const safeId = prop.replace(/[^a-zA-Z0-9-]/g, '_');
            html += `<div class="property-row">`;
            html += `<div class="property-name" title="Click to copy" onclick="copyToClipboard('${prop}')">${prop}</div>`;
            html += `<div id="val_${safeId}" class="property-value" data-property="${prop}">—</div>`;
            html += `</div>`;
        }
        
        html += `</div></div>`;
    }
    
    container.innerHTML = html;
}

// ========== ПОЛУЧЕНИЕ ВСЕХ СВОЙСТВ ==========
async function getAllProperties() {
    if (propertyList.length === 0) {
        alert('Please load property list first');
        return;
    }
    
    document.getElementById('status').innerHTML = '<span class="loading">Getting all property values...</span>';
    
    const result = await apiCall('/api/get_all_properties', propertyList);
    
    if (result.error) {
        document.getElementById('status').innerHTML = `<span class="error">Error: ${result.error}</span>`;
        return;
    }
    
    let updatedCount = 0;
    for (const [prop, value] of Object.entries(result.values || {})) {
        const cell = document.getElementById(`val_${prop.replace(/[^a-zA-Z0-9-]/g, '_')}`);
        if (cell) {
            cell.innerHTML = renderNestedDiv(value);
            updatedCount++;
        }
    }
    
    document.getElementById('status').innerHTML = `<span class="success">Updated ${updatedCount} property values</span>`;
}

// ========== ФИЛЬТРАЦИЯ СВОЙСТВ ==========
function filterProperties(searchTerm) {
    const rows = document.querySelectorAll('.property-row');
    const groups = document.querySelectorAll('.group-container');
    
    rows.forEach(row => {
        const name = row.querySelector('.property-name').textContent.toLowerCase();
        if (name.includes(searchTerm.toLowerCase())) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
    
    // Скрываем пустые группы
    groups.forEach(group => {
        const visibleRows = group.querySelectorAll('.property-row:not([style*="display: none"])');
        if (visibleRows.length === 0) {
            group.style.display = 'none';
        } else {
            group.style.display = '';
        }
    });
}

// ========== СВОРАЧИВАНИЕ/РАЗВОРАЧИВАНИЕ ВСЕХ ГРУПП ==========
function toggleAllGroups(expand = true) {
    const groups = document.querySelectorAll('.group-container');
    groups.forEach(group => {
        const content = group.querySelector('.properties-grid');
        const header = group.querySelector('.group-header');
        if (expand) {
            content.style.display = '';
            header.classList.remove('collapsed');
        } else {
            content.style.display = 'none';
            header.classList.add('collapsed');
        }
    });
}

// ========== ИНИЦИАЛИЗАЦИЯ ==========
window.onload = () => {
    getPropertyList();
    
    // Добавляем поле поиска
    const controls = document.getElementById('controls');
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = '🔍 Filter properties...';
    searchInput.className = 'search-input';
    searchInput.oninput = (e) => filterProperties(e.target.value);
    controls.appendChild(searchInput);
    
    // Кнопки управления группами
    const expandAllBtn = document.createElement('button');
    expandAllBtn.textContent = 'Expand All';
    expandAllBtn.onclick = () => toggleAllGroups(true);
    
    const collapseAllBtn = document.createElement('button');
    collapseAllBtn.textContent = 'Collapse All';
    collapseAllBtn.onclick = () => toggleAllGroups(false);
    
    controls.appendChild(expandAllBtn);
    controls.appendChild(collapseAllBtn);
};
    </script>
</body>
</html>
"""

class MPVClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.request_id = 0
        self.lock = threading.Lock()
    
    def _send_command(self, command):
        """Отправляет команду в MPV и возвращает ответ"""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(self.socket_path)
            
            with self.lock:
                self.request_id += 1
                req_id = self.request_id
            
            request = {"command": command, "request_id": req_id}
            sock.send((json.dumps(request) + "\n").encode())
            
            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break
            
            sock.close()
            
            if response_data:
                return json.loads(response_data.decode().strip())
            return {"error": "no response"}
            
        except FileNotFoundError:
            return {"error": f"Socket {self.socket_path} not found. Is MPV running with --input-ipc-server={self.socket_path}?"}
        except socket.timeout:
            return {"error": "Connection timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    def get_property_list(self):
        """Получает список всех свойств"""
        return self._send_command(["get_property", "property-list"])
    
    def get_property(self, name):
        """Получает значение одного свойства"""
        return self._send_command(["get_property", name])
    
    def get_all_properties(self, properties):
        """Получает значения всех указанных свойств"""
        result = {}
        for prop in properties:
            resp = self.get_property(prop)
            if "data" in resp:
                result[prop] = resp["data"]
            else:
                result[prop] = None
        return result

class MPVHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
            
        elif parsed.path == "/api/get_property_list":
            mpv = MPVClient(SOCKET_PATH)
            response = mpv.get_property_list()
            self._send_json(response)
            
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/get_all_properties":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            try:
                properties = json.loads(body.decode())
                mpv = MPVClient(SOCKET_PATH)
                values = mpv.get_all_properties(properties)
                self._send_json({"values": values, "error": None})
            except Exception as e:
                self._send_json({"error": str(e)})
                
        else:
            self.send_error(404)
    
    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
#    def log_message(self, format, *args):
        # Подавляем стандартный вывод логов
#        pass

def main():
    # Проверяем существование сокета
    if not os.path.exists(SOCKET_PATH):
        print(f"Warning: Socket {SOCKET_PATH} does not exist.")
        print(f"Start MPV with: mpv --input-ipc-server={SOCKET_PATH}")
    
    server = HTTPServer(('0.0.0.0', 8081), MPVHandler)
    print(f"Server running at http://0.0.0.0:8081")
    print(f"MPV socket: {SOCKET_PATH}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
