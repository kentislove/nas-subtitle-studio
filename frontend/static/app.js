const state = {
  videos: [],
  selected: null,
  selectedId: null,
  recording: false,
  startedAt: null,
  recorder: null,
  chunks: [],
  streams: [],
  audioContext: null,
  audioSources: [],
  waveform: null,
  waveformLoading: false,
  timelineZoom: 1,
  timelineDrag: null,
  suppressTimelineClick: false,
  subtitlePreview: false,
  subtitlePreviewUrl: null,
};

const statusText = {
  uploaded: '已上傳',
  preparing: '檢查中',
  transcoding: '轉檔中',
  ready: '可處理',
  captioning: '產字幕中',
  editable: '可編輯',
  exporting: '匯出中',
  exported: '已匯出',
  failed: '失敗',
};

const statusHint = {
  uploaded: '影片已接收，等待後端開始檢查。',
  preparing: '正在檢查影片長度與格式，錄影檔會先轉成標準 MP4。',
  transcoding: '此格式需要轉成 MP4，完成後才能產生字幕。',
  ready: '影片已準備完成，可以產生字幕。',
  captioning: 'Gemini 正在分析影片並產生逐字稿、字幕與章節。',
  editable: '字幕已產生，可以編輯或匯出含字幕 MP4。',
  exporting: '正在燒錄字幕並匯出 MP4，這一步會重新編碼影片。',
  exported: '含字幕 MP4 已匯出，可以下載。',
  failed: '處理失敗，請查看錯誤訊息。',
};

const $ = (id) => document.getElementById(id);

function showMessage(text) {
  const el = $('message');
  if (!text) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.textContent = text;
  el.classList.remove('hidden');
}

function getRecordingUnavailableMessage() {
  if (!window.isSecureContext) {
    return [
      '目前瀏覽器未開放螢幕錄影功能。',
      '原因：你正在用內網 HTTP 開啟此工具，Chrome/Edge 只允許 HTTPS 或 localhost 使用螢幕錄影。',
      '可先用「上傳影片」處理桌面錄影；若要直接在此頁錄影，請改用 HTTPS，或用 Chrome 安全來源例外啟動此內網網址。',
    ].join('\n');
  }
  return '目前瀏覽器不支援螢幕錄影 API，請改用最新版 Chrome 或 Edge。';
}

function canRecordScreen() {
  return Boolean(
    window.isSecureContext
    && navigator.mediaDevices
    && typeof navigator.mediaDevices.getDisplayMedia === 'function'
    && typeof window.MediaRecorder === 'function'
  );
}

function updateRecordingAvailability() {
  const button = $('recordBtn');
  if (!button) return;
  if (canRecordScreen()) {
    button.disabled = false;
    button.title = '';
    return;
  }
  button.disabled = false;
  button.title = '目前網址不是安全來源，按下會顯示處理方式。';
}

function fmtTime(value) {
  const totalMs = Math.max(0, Math.round((Number(value) || 0) * 1000));
  const ms = totalMs % 1000;
  const totalSec = Math.floor(totalMs / 1000);
  const sec = totalSec % 60;
  const min = Math.floor(totalSec / 60);
  return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function fmtVttTime(value) {
  const totalMs = Math.max(0, Math.round((Number(value) || 0) * 1000));
  const ms = totalMs % 1000;
  const totalSeconds = Math.floor(totalMs / 1000);
  const sec = totalSeconds % 60;
  const min = Math.floor(totalSeconds / 60) % 60;
  const hour = Math.floor(totalSeconds / 3600);
  return `${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function parseTime(value) {
  const text = String(value || '').trim();
  const parts = text.split(':');
  if (parts.length === 1) return Number(text) || 0;
  return (Number(parts[0]) || 0) * 60 + (Number(parts[1]) || 0);
}

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  return res.json();
}

function uploadWithProgress(blob, filename) {
  return new Promise((resolve, reject) => {
    const body = new FormData();
    body.append('file', blob, filename);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/videos/upload');
    xhr.timeout = 30 * 60 * 1000;
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        showMessage(`正在上傳影片... ${Math.round(blob.size / 1024 / 1024 * 10) / 10} MB`);
        return;
      }
      const percent = Math.round((event.loaded / event.total) * 100);
      const loaded = Math.round(event.loaded / 1024 / 1024 * 10) / 10;
      const total = Math.round(event.total / 1024 / 1024 * 10) / 10;
      showMessage(`正在上傳影片... ${percent}%（${loaded} / ${total} MB）`);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error('上傳成功，但伺服器回傳格式無法解析'));
        }
        return;
      }
      try {
        const data = JSON.parse(xhr.responseText);
        reject(new Error(data.detail || xhr.statusText || '上傳失敗'));
      } catch {
        reject(new Error(xhr.statusText || '上傳失敗'));
      }
    };
    xhr.onerror = () => reject(new Error('上傳連線中斷，請檢查 NAS 連線'));
    xhr.ontimeout = () => reject(new Error('上傳逾時，請檢查 NAS 網路或檔案大小'));
    xhr.send(body);
  });
}

function downloadUrl(kind) {
  return state.selected ? `/api/videos/${state.selected.id}/download/${kind}` : '#';
}

function setDownloadLink(id, href, enabled = true) {
  const link = $(id);
  link.href = enabled ? href : '#';
  link.classList.toggle('disabled-link', !enabled);
  link.onclick = enabled ? null : (event) => {
    event.preventDefault();
    showMessage('檔案尚未產生完成');
  };
}

function mediaUrl(video) {
  return `/media/videos/${video.stored_filename}`;
}

function isProcessingStatus(status) {
  return ['uploaded', 'preparing', 'transcoding', 'captioning', 'exporting'].includes(status);
}

function setPlayerSource(video) {
  const player = $('player');
  const url = mediaUrl(video);
  if (player.getAttribute('src') !== url) {
    player.src = url;
    player.load();
  }
}

function revokeSubtitlePreviewUrl() {
  if (state.subtitlePreviewUrl) {
    URL.revokeObjectURL(state.subtitlePreviewUrl);
    state.subtitlePreviewUrl = null;
  }
}

function buildPreviewVtt(video) {
  const blocks = ['WEBVTT\n'];
  [...(video.subtitles || [])]
    .filter((seg) => seg.text && Number(seg.end) > Number(seg.start))
    .sort((a, b) => Number(a.start) - Number(b.start))
    .forEach((seg) => {
      const text = String(seg.text)
        .replace(/\r\n?/g, '\n')
        .replace(/-->/g, '->')
        .trim();
      if (!text) return;
      blocks.push(`${fmtVttTime(seg.start)} --> ${fmtVttTime(seg.end)}\n${text}\n`);
    });
  return blocks.join('\n');
}

function removePreviewTrack() {
  const track = $('player').querySelector('track[data-preview-subtitles="true"]');
  if (track) {
    track.track.mode = 'disabled';
    track.remove();
  }
  revokeSubtitlePreviewUrl();
}

function refreshSubtitlePreview(video = state.selected) {
  const button = $('previewSubtitleBtn');
  const player = $('player');
  if (!button || !player) return;
  const hasSubtitles = Boolean(video?.subtitles?.length);
  if (!hasSubtitles) {
    state.subtitlePreview = false;
    button.disabled = true;
    button.classList.remove('active');
    button.textContent = '顯示預覽字幕';
    button.title = '尚無字幕可預覽';
    removePreviewTrack();
    return;
  }

  button.disabled = false;
  button.classList.toggle('active', state.subtitlePreview);
  button.textContent = state.subtitlePreview ? '隱藏預覽字幕' : '顯示預覽字幕';
  button.title = state.subtitlePreview ? '關閉影片上的字幕預覽' : '在上方影片顯示目前字幕';

  if (!state.subtitlePreview) {
    removePreviewTrack();
    return;
  }

  removePreviewTrack();
  const blob = new Blob([buildPreviewVtt(video)], { type: 'text/vtt;charset=utf-8' });
  state.subtitlePreviewUrl = URL.createObjectURL(blob);
  const track = document.createElement('track');
  track.dataset.previewSubtitles = 'true';
  track.kind = 'subtitles';
  track.label = '字幕預覽';
  track.srclang = 'zh-Hant';
  track.src = state.subtitlePreviewUrl;
  player.appendChild(track);
  track.track.mode = 'showing';
  track.onload = () => {
    track.track.mode = 'showing';
  };
}

function refreshPreviewIfEnabled() {
  if (state.subtitlePreview) refreshSubtitlePreview();
}

function cleanupRecordingResources() {
  state.streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
  state.streams = [];
  if (state.audioContext) {
    state.audioContext.close().catch(() => undefined);
    state.audioContext = null;
  }
  state.audioSources = [];
}

async function createRecordingStream() {
  const screen = await navigator.mediaDevices.getDisplayMedia({
    video: { frameRate: 30 },
    audio: true,
  });
  state.streams = [screen];

  const videoTracks = screen.getVideoTracks();
  const audioTracks = [...screen.getAudioTracks()];
  try {
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    audioTracks.push(...mic.getAudioTracks());
    state.streams.push(mic);
  } catch {
    showMessage('未取得麥克風，將只錄畫面或分頁音訊');
  }

  if (audioTracks.length <= 1) {
    return new MediaStream([...videoTracks, ...audioTracks]);
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    return new MediaStream([...videoTracks, audioTracks[0]]);
  }

  const audioContext = new AudioContextClass();
  const destination = audioContext.createMediaStreamDestination();
  state.audioSources = [];
  audioTracks.forEach((track) => {
    const source = audioContext.createMediaStreamSource(new MediaStream([track]));
    source.connect(destination);
    state.audioSources.push(source);
  });
  state.audioContext = audioContext;
  return new MediaStream([...videoTracks, ...destination.stream.getAudioTracks()]);
}

async function loadHealth() {
  try {
    const health = await request('/api/health');
    const el = $('geminiStatus');
    el.textContent = `Gemini ${health.gemini_configured ? '已設定' : '未設定'}`;
    el.className = `pill ${health.gemini_configured ? 'ok' : 'warn'}`;
  } catch {
    $('geminiStatus').textContent = 'API 未連線';
  }
}

async function saveGeminiSettings() {
  const apiKey = $('geminiApiKey').value.trim();
  if (!apiKey) {
    showMessage('請先輸入 Gemini API Key');
    return;
  }
  const result = await request('/api/settings/gemini', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  });
  $('geminiApiKey').value = '';
  const el = $('geminiStatus');
  el.textContent = `Gemini ${result.gemini_configured ? '已設定' : '未設定'}`;
  el.className = `pill ${result.gemini_configured ? 'ok' : 'warn'}`;
  showMessage('Gemini API Key 已儲存到 NAS');
}

async function loadVideos(options = {}) {
  const refreshSelected = options.refreshSelected ?? true;
  state.videos = await request('/api/videos');
  renderVideoList();
  if (state.selectedId) {
    const summary = state.videos.find((video) => video.id === state.selectedId);
    if (summary) {
      const shouldRefreshSelected = refreshSelected
        || isProcessingStatus(summary.status)
        || isProcessingStatus(state.selected?.status);
      if (!shouldRefreshSelected) return;
      await loadSelected(state.selectedId);
    } else {
      clearSelected();
    }
  }
}

async function loadSelected(id) {
  if (!id) return;
  const previous = state.selected;
  const next = await request(`/api/videos/${id}`);
  const sameMedia = previous?.id === next.id && previous?.stored_filename === next.stored_filename;
  if (!sameMedia) {
    state.waveform = null;
    state.subtitlePreview = false;
    removePreviewTrack();
  }
  state.selected = next;
  renderSelected();
  if (!sameMedia || !state.waveform) {
    loadWaveform(id).catch((e) => showMessage(e.message));
  }
}

function clearSelected() {
  state.selected = null;
  state.selectedId = null;
  state.subtitlePreview = false;
  removePreviewTrack();
  $('player').removeAttribute('src');
  $('player').load();
  renderVideoList();
  renderSelected();
}

function renderVideoList() {
  const list = $('videoList');
  list.innerHTML = '';
  if (!state.videos.length) {
    list.innerHTML = '<p class="empty">尚無影片</p>';
    return;
  }
  state.videos.forEach((video) => {
    const btn = document.createElement('button');
    btn.className = `video-item ${state.selectedId === video.id ? 'active' : ''}`;
    btn.innerHTML = `
      <span class="video-title"></span>
      <span class="status ${video.status}">${statusText[video.status] || video.status}</span>
    `;
    btn.querySelector('.video-title').textContent = video.title;
    btn.onclick = async () => {
      state.selectedId = video.id;
      await loadSelected(video.id);
      renderVideoList();
    };
    list.appendChild(btn);
  });
}

function renderSelected() {
  const video = state.selected;
  $('blankState').classList.toggle('hidden', !!video);
  $('viewerBand').classList.toggle('hidden', !video);
  $('editorLayout').classList.toggle('hidden', !video);
  if (!video) return;

  setPlayerSource(video);
  refreshSubtitlePreview(video);
  $('videoTitle').textContent = video.title;
  $('videoFilename').textContent = video.filename;
  $('videoStatus').textContent = statusText[video.status] || video.status;
  $('processingStatus').textContent = statusHint[video.status] || '';
  $('videoDuration').textContent = video.duration ? `長度：${fmtTime(video.duration)}` : '';
  $('videoError').textContent = video.error || '';
  $('transcript').value = video.transcript || '';

  $('captionBtn').disabled = !['ready', 'editable', 'exported', 'failed'].includes(video.status);
  $('importSubtitleBtn').disabled = !video;
  $('saveBtn').disabled = !video.subtitles.length;
  $('exportBtn').disabled = !video.subtitles.length;
  $('deleteVideoBtn').disabled = false;

  setDownloadLink('downloadVideo', downloadUrl('video'), true);
  setDownloadLink('downloadSrt', downloadUrl('srt'), Boolean(video.subtitles.length));
  setDownloadLink('downloadVtt', downloadUrl('vtt'), Boolean(video.subtitles.length));
  setDownloadLink('downloadTxt', downloadUrl('txt'), Boolean(video.transcript));
  setDownloadLink('downloadChapters', downloadUrl('chapters'), Boolean(video.chapters.length));
  setDownloadLink('downloadExport', downloadUrl('export'), video.status === 'exported');

  renderSubtitles();
  renderTimeline();
  renderChapters();
}

async function loadWaveform(id) {
  if (!id) return;
  state.waveformLoading = true;
  renderTimeline();
  try {
    const waveform = await request(`/api/videos/${id}/waveform?points=2400`);
    if (!state.selected || state.selected.id !== id) return;
    state.waveform = waveform;
  } finally {
    state.waveformLoading = false;
    renderTimeline();
  }
}

function getTimelineDuration() {
  const video = state.selected;
  const playerDuration = $('player').duration;
  const lastSubtitleEnd = Math.max(0, ...(video?.subtitles || []).map((seg) => Number(seg.end) || 0));
  return Math.max(1, Number(video?.duration) || 0, Number.isFinite(playerDuration) ? playerDuration : 0, lastSubtitleEnd);
}

function getTimelineScale() {
  const viewport = $('timelineViewport');
  const duration = getTimelineDuration();
  const visibleWidth = Math.max(420, viewport.clientWidth || 420);
  const width = Math.max(visibleWidth, Math.ceil(duration * 18 * state.timelineZoom));
  return { duration, width, pxPerSecond: width / duration };
}

function setTimelineZoom(nextZoom) {
  const viewport = $('timelineViewport');
  const currentTime = $('player').currentTime || 0;
  state.timelineZoom = Math.max(0.5, Math.min(8, nextZoom));
  renderTimeline();
  const { pxPerSecond } = getTimelineScale();
  viewport.scrollLeft = Math.max(0, currentTime * pxPerSecond - viewport.clientWidth * 0.42);
}

function fitTimelineZoom() {
  const duration = getTimelineDuration();
  const viewport = $('timelineViewport');
  const fitZoom = (viewport.clientWidth || 420) / Math.max(1, duration * 18);
  setTimelineZoom(fitZoom);
}

function renderTimeline() {
  const video = state.selected;
  const viewport = $('timelineViewport');
  const canvas = $('timelineCanvas');
  const ruler = $('timelineRuler');
  const tracks = $('timelineTracks');
  const waveform = $('timelineWaveform');
  if (!viewport || !canvas || !ruler || !tracks || !waveform) return;
  ruler.innerHTML = '';
  tracks.innerHTML = '';
  if (!video) {
    canvas.style.width = '100%';
    viewport.classList.add('hidden');
    return;
  }
  viewport.classList.remove('hidden');
  const { duration, width, pxPerSecond } = getTimelineScale();
  canvas.style.width = `${width}px`;

  const tickStep = duration > 900 ? 120 : duration > 300 ? 60 : duration > 90 ? 15 : 5;
  for (let time = 0; time <= duration; time += tickStep) {
    const tick = document.createElement('span');
    tick.className = 'timeline-tick';
    tick.style.left = `${time * pxPerSecond}px`;
    tick.textContent = fmtTime(time).replace('.000', '');
    ruler.appendChild(tick);
  }
  renderWaveform(width);

  if (!video.subtitles.length) {
    const track = document.createElement('div');
    track.className = 'timeline-track empty-track';
    tracks.appendChild(track);
  }
  video.subtitles.forEach((seg, index) => {
    const track = document.createElement('div');
    track.className = 'timeline-track';
    const label = document.createElement('span');
    label.className = 'timeline-label';
    label.textContent = String(index + 1);
    const clip = document.createElement('div');
    clip.className = `timeline-clip ${isSubtitleActive(seg) ? 'active' : ''}`;
    clip.dataset.id = seg.id;
    const left = Math.max(0, seg.start * pxPerSecond);
    const clipWidth = Math.max(18, (seg.end - seg.start) * pxPerSecond);
    clip.style.left = `${left}px`;
    clip.style.width = `${clipWidth}px`;
    clip.innerHTML = `
      <span class="timeline-handle start" data-action="start"></span>
      <span class="timeline-clip-label"></span>
      <span class="timeline-handle end" data-action="end"></span>
    `;
    clip.querySelector('.timeline-clip-label').textContent = seg.text || '字幕';
    clip.onpointerdown = (event) => startTimelineDrag(event, seg.id, event.target.dataset.action || 'move');
    track.appendChild(label);
    track.appendChild(clip);
    tracks.appendChild(track);
  });
  updateTimelinePlayhead();
}

function renderWaveform(width) {
  const canvas = $('timelineWaveform');
  if (!canvas) return;
  const height = 74;
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  canvas.width = Math.max(1, Math.floor(width * dpr));
  canvas.height = Math.floor(height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#fbfdfd';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = '#d3dde2';
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();
  if (state.waveformLoading && !state.waveform) {
    ctx.fillStyle = '#65747e';
    ctx.font = '13px Segoe UI, Arial';
    ctx.fillText('正在產生音訊波形...', 12, 28);
    return;
  }
  const peaks = state.waveform?.peaks || [];
  if (!peaks.length) {
    ctx.fillStyle = '#65747e';
    ctx.font = '13px Segoe UI, Arial';
    ctx.fillText('尚無音訊波形', 12, 28);
    return;
  }
  const barWidth = Math.max(1, width / peaks.length);
  ctx.fillStyle = '#4f8f87';
  peaks.forEach((peak, index) => {
    const x = index * barWidth;
    const h = Math.max(1, peak * (height - 16));
    ctx.fillRect(x, (height - h) / 2, Math.max(1, barWidth * 0.75), h);
  });
}

function isSubtitleActive(seg) {
  const time = $('player').currentTime || 0;
  return time >= seg.start && time <= seg.end;
}

function updateTimelinePlayhead() {
  const playhead = $('timelinePlayhead');
  const clock = $('timelineClock');
  if (!playhead || !clock || !state.selected) return;
  const { pxPerSecond } = getTimelineScale();
  const time = $('player').currentTime || 0;
  playhead.style.left = `${time * pxPerSecond}px`;
  clock.textContent = fmtTime(time);
  document.querySelectorAll('.timeline-clip').forEach((clip) => {
    const seg = state.selected?.subtitles.find((item) => item.id === clip.dataset.id);
    clip.classList.toggle('active', Boolean(seg && isSubtitleActive(seg)));
  });
}

function updateSubtitleInputs(seg) {
  const row = document.querySelector(`.subtitle-row[data-segment-id="${seg.id}"]`);
  if (!row) return;
  row.querySelector('.start').value = fmtTime(seg.start);
  row.querySelector('.end').value = fmtTime(seg.end);
}

function updateTimelineClip(seg) {
  const clip = document.querySelector(`.timeline-clip[data-id="${seg.id}"]`);
  if (!clip) return;
  const { pxPerSecond } = getTimelineScale();
  clip.style.left = `${Math.max(0, seg.start * pxPerSecond)}px`;
  clip.style.width = `${Math.max(18, (seg.end - seg.start) * pxPerSecond)}px`;
}

function startTimelineDrag(event, segmentId, action) {
  if (!state.selected) return;
  const seg = state.selected.subtitles.find((item) => item.id === segmentId);
  if (!seg) return;
  event.preventDefault();
  event.currentTarget.setPointerCapture(event.pointerId);
  state.timelineDrag = {
    id: segmentId,
    action,
    startX: event.clientX,
    start: seg.start,
    end: seg.end,
    pxPerSecond: getTimelineScale().pxPerSecond,
  };
}

function startTimelinePan(event) {
  if (!state.selected || event.target.closest('.timeline-clip')) return;
  state.timelineDrag = {
    action: 'pan',
    startX: event.clientX,
    scrollLeft: $('timelineViewport').scrollLeft,
    moved: false,
  };
}

function moveTimelineDrag(event) {
  if (!state.timelineDrag || !state.selected) return;
  const drag = state.timelineDrag;
  if (drag.action === 'pan') {
    const deltaX = event.clientX - drag.startX;
    if (Math.abs(deltaX) > 3) drag.moved = true;
    $('timelineViewport').scrollLeft = Math.max(0, drag.scrollLeft - deltaX);
    return;
  }
  const seg = state.selected.subtitles.find((item) => item.id === drag.id);
  if (!seg) return;
  const delta = (event.clientX - drag.startX) / drag.pxPerSecond;
  const duration = getTimelineDuration();
  const minLength = 0.15;
  if (drag.action === 'start') {
    seg.start = Math.min(Math.max(0, drag.start + delta), seg.end - minLength);
  } else if (drag.action === 'end') {
    seg.end = Math.max(seg.start + minLength, Math.min(duration, drag.end + delta));
  } else {
    const length = drag.end - drag.start;
    const nextStart = Math.min(Math.max(0, drag.start + delta), Math.max(0, duration - length));
    seg.start = nextStart;
    seg.end = nextStart + length;
  }
  updateTimelineClip(seg);
  updateSubtitleInputs(seg);
}

function stopTimelineDrag() {
  const action = state.timelineDrag?.action;
  if (action === 'pan' && state.timelineDrag.moved) {
    state.suppressTimelineClick = true;
    window.setTimeout(() => {
      state.suppressTimelineClick = false;
    }, 0);
  }
  state.timelineDrag = null;
  if (action && action !== 'pan') refreshPreviewIfEnabled();
}

function renderSubtitles() {
  const list = $('subtitleList');
  const video = state.selected;
  list.innerHTML = '';
  if (!video || !video.subtitles.length) {
    list.innerHTML = '<p class="empty">尚無字幕，請先產生或新增字幕。</p>';
    return;
  }
  video.subtitles.forEach((seg) => {
    const row = document.createElement('div');
    row.className = 'subtitle-row';
    row.dataset.segmentId = seg.id;
    row.innerHTML = `
      <button class="jump">播放</button>
      <input class="start" value="${fmtTime(seg.start)}" />
      <input class="end" value="${fmtTime(seg.end)}" />
      <textarea class="text"></textarea>
      <button class="remove">刪除</button>
    `;
    row.querySelector('.text').value = seg.text;
    row.querySelector('.jump').onclick = () => {
      $('player').currentTime = seg.start;
      $('player').play();
    };
    row.querySelector('.start').onchange = (e) => {
      seg.start = parseTime(e.target.value);
      e.target.value = fmtTime(seg.start);
      renderTimeline();
      refreshPreviewIfEnabled();
    };
    row.querySelector('.end').onchange = (e) => {
      seg.end = parseTime(e.target.value);
      e.target.value = fmtTime(seg.end);
      renderTimeline();
      refreshPreviewIfEnabled();
    };
    row.querySelector('.text').oninput = (e) => {
      seg.text = e.target.value;
      const label = document.querySelector(`.timeline-clip[data-id="${seg.id}"] .timeline-clip-label`);
      if (label) label.textContent = seg.text || '字幕';
      refreshPreviewIfEnabled();
    };
    row.querySelector('.remove').onclick = () => {
      video.subtitles = video.subtitles.filter((item) => item.id !== seg.id);
      renderSubtitles();
      renderTimeline();
      refreshPreviewIfEnabled();
    };
    list.appendChild(row);
  });
}

function renderChapters() {
  const list = $('chapterList');
  const video = state.selected;
  list.innerHTML = '';
  if (!video || !video.chapters.length) {
    list.innerHTML = '<p class="empty">尚無章節。</p>';
    return;
  }
  video.chapters.forEach((chapter) => {
    const row = document.createElement('div');
    row.className = 'chapter-row';
    row.innerHTML = `
      <input class="chapter-time" value="${fmtTime(chapter.start)}" />
      <input class="chapter-title" />
    `;
    row.querySelector('.chapter-title').value = chapter.title;
    row.querySelector('.chapter-time').onchange = (e) => {
      chapter.start = parseTime(e.target.value);
      e.target.value = fmtTime(chapter.start);
    };
    row.querySelector('.chapter-title').oninput = (e) => {
      chapter.title = e.target.value;
    };
    list.appendChild(row);
  });
}

async function uploadBlob(blob, filename) {
  const sizeMb = Math.round(blob.size / 1024 / 1024 * 10) / 10;
  if (!blob.size) {
    throw new Error('錄影檔案是空的，請重新錄影。');
  }
  showMessage(`正在上傳影片... 0%（${sizeMb} MB）`);
  const record = await uploadWithProgress(blob, filename);
  state.selectedId = record.id;
  await loadVideos();
  showMessage('影片已上傳，系統正在檢查格式。錄影產生的 webm 會直接進入可處理狀態。');
}

async function startRecording() {
  try {
    showMessage('');
    if (!canRecordScreen()) {
      showMessage(getRecordingUnavailableMessage());
      return;
    }
    const stream = await createRecordingStream();
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
      ? 'video/webm;codecs=vp9,opus'
      : 'video/webm';
    state.chunks = [];
    state.recorder = new MediaRecorder(stream, { mimeType });
    state.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) state.chunks.push(event.data);
    };
    state.recorder.onstop = async () => {
      const blob = new Blob(state.chunks, { type: 'video/webm' });
      cleanupRecordingResources();
      state.recording = false;
      state.startedAt = null;
      $('recordBtn').textContent = '開始錄影';
      $('recordBtn').className = 'primary';
      $('timer').textContent = '00:00.000';
      try {
        await uploadBlob(blob, `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`);
      } catch (e) {
        showMessage(e.message);
      }
    };
    state.recorder.start(1000);
    state.recording = true;
    state.startedAt = Date.now();
    $('recordBtn').textContent = '停止並上傳';
    $('recordBtn').className = 'danger';
  } catch (e) {
    cleanupRecordingResources();
    showMessage(e.message);
  }
}

function stopRecording() {
  state.recorder?.stop();
}

async function saveSubtitles() {
  if (!state.selected) return;
  state.selected.transcript = $('transcript').value;
  const updated = await request(`/api/videos/${state.selected.id}/subtitles`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      subtitles: state.selected.subtitles,
      transcript: state.selected.transcript,
      chapters: state.selected.chapters,
    }),
  });
  state.selected = updated;
  renderSelected();
  showMessage('字幕已儲存');
}

async function importSubtitleFile(file) {
  if (!state.selected || !file) return;
  const body = new FormData();
  body.append('file', file, file.name);
  showMessage(`正在匯入字幕：${file.name}`);
  const res = await fetch(`/api/videos/${state.selected.id}/subtitles/import`, {
    method: 'POST',
    body,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
  state.selected = await res.json();
  renderSelected();
  showMessage(`字幕已匯入，共 ${state.selected.subtitles.length} 段`);
}

function addSubtitle() {
  if (!state.selected) return;
  const last = state.selected.subtitles[state.selected.subtitles.length - 1];
  const start = last ? last.end : Math.floor($('player').currentTime || 0);
  state.selected.subtitles.push({ id: crypto.randomUUID(), start, end: start + 3, text: '新增字幕' });
  renderSubtitles();
  renderTimeline();
  refreshPreviewIfEnabled();
}

function addChapter() {
  if (!state.selected) return;
  state.selected.chapters.push({ start: Math.floor($('player').currentTime || 0), title: '新增章節' });
  renderChapters();
}

async function captionSelected() {
  if (!state.selected) return;
  const health = await request('/api/health');
  if (!health.gemini_configured) {
    showMessage('尚未設定 Gemini API Key，請先在左側 Gemini API 欄位輸入並儲存。');
    return;
  }
  await request(`/api/videos/${state.selected.id}/caption`, { method: 'POST' });
  showMessage('已排入產字幕流程');
  await loadSelected(state.selected.id);
}

async function exportSelected() {
  if (!state.selected) return;
  await saveSubtitles();
  await request(`/api/videos/${state.selected.id}/export`, { method: 'POST' });
  showMessage('已排入含字幕影片匯出流程');
  await loadSelected(state.selected.id);
}

async function deleteSelectedVideo() {
  if (!state.selected) return;
  const title = state.selected.title;
  if (!window.confirm(`確定刪除「${title}」？影片、字幕與匯出檔都會刪除。`)) return;
  await request(`/api/videos/${state.selected.id}`, { method: 'DELETE' });
  showMessage('影片已刪除');
  clearSelected();
  await loadVideos();
}

function bindEvents() {
  $('recordBtn').onclick = () => (state.recording ? stopRecording() : startRecording());
  $('fileInput').onchange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      await uploadBlob(file, file.name);
    } catch (e) {
      showMessage(e.message);
    } finally {
      event.target.value = '';
    }
  };
  $('refreshBtn').onclick = () => loadVideos().catch((e) => showMessage(e.message));
  $('captionBtn').onclick = () => captionSelected().catch((e) => showMessage(e.message));
  $('importSubtitleBtn').onclick = () => {
    if (!state.selected) {
      showMessage('請先選擇影片');
      return;
    }
    $('subtitleFileInput').click();
  };
  $('subtitleFileInput').onchange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      await importSubtitleFile(file);
    } catch (e) {
      showMessage(e.message);
    } finally {
      event.target.value = '';
    }
  };
  $('saveBtn').onclick = () => saveSubtitles().catch((e) => showMessage(e.message));
  $('exportBtn').onclick = () => exportSelected().catch((e) => showMessage(e.message));
  $('deleteVideoBtn').onclick = () => deleteSelectedVideo().catch((e) => showMessage(e.message));
  $('addSubtitleBtn').onclick = addSubtitle;
  $('addChapterBtn').onclick = addChapter;
  $('previewSubtitleBtn').onclick = () => {
    if (!state.selected?.subtitles?.length) {
      showMessage('尚無字幕可預覽');
      return;
    }
    state.subtitlePreview = !state.subtitlePreview;
    refreshSubtitlePreview();
  };
  $('saveGeminiBtn').onclick = () => saveGeminiSettings().catch((e) => showMessage(e.message));
  $('player').ontimeupdate = updateTimelinePlayhead;
  $('player').onloadedmetadata = () => {
    renderTimeline();
    updateTimelinePlayhead();
  };
  window.onpointermove = moveTimelineDrag;
  window.onpointerup = stopTimelineDrag;
  $('timelineZoomOutBtn').onclick = () => setTimelineZoom(state.timelineZoom / 1.35);
  $('timelineZoomInBtn').onclick = () => setTimelineZoom(state.timelineZoom * 1.35);
  $('timelineFitBtn').onclick = fitTimelineZoom;
  $('timelineViewport').onpointerdown = startTimelinePan;
  $('timelineViewport').onclick = (event) => {
    if (!state.selected || event.target.closest('.timeline-clip')) return;
    if (state.suppressTimelineClick) return;
    const rect = $('timelineCanvas').getBoundingClientRect();
    const { pxPerSecond } = getTimelineScale();
    $('player').currentTime = Math.max(0, (event.clientX - rect.left) / pxPerSecond);
    updateTimelinePlayhead();
  };
}

function startPolling() {
  window.setInterval(() => {
    if (state.startedAt) {
      $('timer').textContent = fmtTime((Date.now() - state.startedAt) / 1000);
    }
    loadVideos({ refreshSelected: false }).catch(() => undefined);
  }, 2500);
}

bindEvents();
updateRecordingAvailability();
loadHealth();
loadVideos().catch((e) => showMessage(e.message));
startPolling();
