const state = {
  videos: [],
  selected: null,
  selectedId: null,
  recording: false,
  startedAt: null,
  recorder: null,
  chunks: [],
  streams: [],
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
  preparing: '正在檢查影片長度與格式。webm/mp4 不會先轉檔，完成後可直接產字幕。',
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

async function loadVideos() {
  state.videos = await request('/api/videos');
  renderVideoList();
  if (state.selectedId) {
    const exists = state.videos.some((video) => video.id === state.selectedId);
    if (exists) {
      await loadSelected(state.selectedId);
    } else {
      clearSelected();
    }
  }
}

async function loadSelected(id) {
  if (!id) return;
  state.selected = await request(`/api/videos/${id}`);
  renderSelected();
}

function clearSelected() {
  state.selected = null;
  state.selectedId = null;
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

  $('player').src = mediaUrl(video);
  $('videoTitle').textContent = video.title;
  $('videoFilename').textContent = video.filename;
  $('videoStatus').textContent = statusText[video.status] || video.status;
  $('processingStatus').textContent = statusHint[video.status] || '';
  $('videoDuration').textContent = video.duration ? `長度：${fmtTime(video.duration)}` : '';
  $('videoError').textContent = video.error || '';
  $('transcript').value = video.transcript || '';

  $('captionBtn').disabled = !['ready', 'editable', 'exported', 'failed'].includes(video.status);
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
  renderChapters();
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
    };
    row.querySelector('.end').onchange = (e) => {
      seg.end = parseTime(e.target.value);
      e.target.value = fmtTime(seg.end);
    };
    row.querySelector('.text').oninput = (e) => {
      seg.text = e.target.value;
    };
    row.querySelector('.remove').onclick = () => {
      video.subtitles = video.subtitles.filter((item) => item.id !== seg.id);
      renderSubtitles();
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
    const screen = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: true });
    const tracks = [...screen.getVideoTracks(), ...screen.getAudioTracks()];
    state.streams = [screen];
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      tracks.push(...mic.getAudioTracks());
      state.streams.push(mic);
    } catch {
      showMessage('未取得麥克風，將只錄畫面或分頁音訊');
    }
    const stream = new MediaStream(tracks);
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
      state.streams.forEach((s) => s.getTracks().forEach((t) => t.stop()));
      state.recording = false;
      state.startedAt = null;
      $('recordBtn').textContent = '開始錄影';
      $('recordBtn').className = 'primary';
      $('timer').textContent = '00:00.000';
      await uploadBlob(blob, `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`);
    };
    state.recorder.start(1000);
    state.recording = true;
    state.startedAt = Date.now();
    $('recordBtn').textContent = '停止並上傳';
    $('recordBtn').className = 'danger';
  } catch (e) {
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
  showMessage('字幕已儲存');
}

function addSubtitle() {
  if (!state.selected) return;
  const last = state.selected.subtitles[state.selected.subtitles.length - 1];
  const start = last ? last.end : Math.floor($('player').currentTime || 0);
  state.selected.subtitles.push({ id: crypto.randomUUID(), start, end: start + 3, text: '新增字幕' });
  renderSubtitles();
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
  $('saveBtn').onclick = () => saveSubtitles().catch((e) => showMessage(e.message));
  $('exportBtn').onclick = () => exportSelected().catch((e) => showMessage(e.message));
  $('deleteVideoBtn').onclick = () => deleteSelectedVideo().catch((e) => showMessage(e.message));
  $('addSubtitleBtn').onclick = addSubtitle;
  $('addChapterBtn').onclick = addChapter;
  $('saveGeminiBtn').onclick = () => saveGeminiSettings().catch((e) => showMessage(e.message));
}

function startPolling() {
  window.setInterval(() => {
    if (state.startedAt) {
      $('timer').textContent = fmtTime((Date.now() - state.startedAt) / 1000);
    }
    loadVideos().catch(() => undefined);
  }, 2500);
}

bindEvents();
updateRecordingAvailability();
loadHealth();
loadVideos().catch((e) => showMessage(e.message));
startPolling();
