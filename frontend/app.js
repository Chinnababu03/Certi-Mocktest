/**
 * CertIQ – Quiz App Frontend Logic
 * Communicates with FastAPI backend at /api/*
 */

const API = 'https://certiq-api-502816012135.asia-south1.run.app';  // Cloud Run API

// ── State ──────────────────────────────────────────────────────
const state = {
  questions: [],
  sessionId: null,
  currentIndex: 0,
  userAnswers: {},    // { questionId: selectedKey }
  revealedAnswers: {}, // { questionId: { correct, selected } }
  timerInterval: null,
  elapsedSeconds: 0,
  quizFinished: false,
  totalQuizzesTaken: parseInt(localStorage.getItem('certiq_total') || '0'),
  categories: [],
};

// ── DOM Refs ───────────────────────────────────────────────────
const screens = {
  home: document.getElementById('screen-home'),
  quiz: document.getElementById('screen-quiz'),
  results: document.getElementById('screen-results'),
};

// ══════════════════════════════════════════════════════════════
// INITIALIZATION
// ══════════════════════════════════════════════════════════════
async function init() {
  setupRingGradient();
  setupSlider();
  await Promise.all([loadStats(), loadCategories()]);
}

function setupRingGradient() {
  // Inject SVG defs into DOM for ring gradient
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
  svg.style.position = 'absolute';
  svg.innerHTML = `
    <defs>
      <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#6366f1"/>
        <stop offset="100%" stop-color="#22d3a5"/>
      </linearGradient>
    </defs>`;
  document.body.appendChild(svg);
}

function setupSlider() {
  const slider = document.getElementById('quiz-count');
  const val = document.getElementById('quiz-count-val');
  slider.addEventListener('input', () => { val.textContent = slider.value; });
}

async function loadStats() {
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    animateNumber('stat-total', data.total_questions || 0);
    document.getElementById('stat-taken').textContent = state.totalQuizzesTaken;
  } catch {
    document.getElementById('stat-total').textContent = '–';
  }
}

async function loadCategories() {
  try {
    const res = await fetch(`${API}/api/categories`);
    const data = await res.json();
    state.categories = data.categories || [];

    animateNumber('stat-topics', state.categories.length);

    // Populate select
    const sel = document.getElementById('topic-select');
    state.categories.forEach(cat => {
      const opt = document.createElement('option');
      opt.value = cat.topic; opt.textContent = `${cat.topic} (${cat.count})`;
      sel.appendChild(opt);
    });

    // Render category grid
    renderCategoryGrid();
  } catch {
    document.getElementById('stat-topics').textContent = '–';
    document.getElementById('category-grid').innerHTML =
      '<p style="color:var(--text-muted);font-size:13px;grid-column:1/-1">Could not load categories.</p>';
  }
}

function renderCategoryGrid() {
  const grid = document.getElementById('category-grid');
  if (!state.categories.length) { grid.innerHTML = ''; return; }

  const colors = ['#6366f1', '#8b5cf6', '#22d3a5', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#10b981'];
  grid.innerHTML = state.categories.map((cat, i) => `
    <div class="category-chip" onclick="quickStartByTopic('${escHtml(cat.topic)}')">
      <div class="cc-dot" style="background:${colors[i % colors.length]}"></div>
      <div class="cc-name">${escHtml(cat.topic)}</div>
      <div class="cc-count">${cat.count} questions</div>
    </div>`).join('');
}

function quickStartByTopic(topic) {
  document.getElementById('topic-select').value = topic;
  startQuiz();
}

// ══════════════════════════════════════════════════════════════
// QUIZ FLOW
// ══════════════════════════════════════════════════════════════
async function startQuiz() {
  const count = parseInt(document.getElementById('quiz-count').value) || 10;
  const topic = document.getElementById('topic-select').value;

  const btn = document.getElementById('btn-start');
  btn.disabled = true; btn.querySelector('span').textContent = 'Loading…';

  try {
    const cert = document.getElementById('cert-select').value;
    let url = `${API}/api/quiz?count=${count}`;
    if (cert) url += `&cert=${encodeURIComponent(cert)}`;
    if (topic) url += `&topic=${encodeURIComponent(topic)}`;

    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch quiz');
    const data = await res.json();

    state.questions = data.questions;
    state.sessionId = data.session_id;
    state.currentIndex = 0;
    state.visited = new Set([0]);
    state.userAnswers = {};
    state.revealedAnswers = {};
    // GCP averages ~144 seconds per question
    state.timeLeft = count * 144;
    state.quizFinished = false;

    showScreen('quiz');
    renderQuestion();
    startTimer();
  } catch (err) {
    showToast('⚠️ Could not load questions. Is the server running?');
  } finally {
    btn.disabled = false; btn.querySelector('span').textContent = 'Start Quiz';
  }
}

function renderQuestion() {
  const q = state.questions[state.currentIndex];
  if (!q) return;

  const total = state.questions.length;
  const idx = state.currentIndex;

  // Header
  document.getElementById('q-counter').textContent = `${idx + 1} / ${total}`;
  document.getElementById('q-topic').textContent = q.topic || 'General';
  document.getElementById('progress-bar').style.width = `${((idx + 1) / total) * 100}%`;

  // Live score
  const correct = Object.values(state.revealedAnswers).filter(r => r.isCorrect).length;
  document.getElementById('live-score').textContent = correct;
  document.getElementById('live-max').textContent = Object.keys(state.revealedAnswers).length;

  // Question text
  const questionCard = document.getElementById('question-card');
  const questionText = document.getElementById('question-text');
  questionCard.classList.add('animating');
  setTimeout(() => questionCard.classList.remove('animating'), 350);
  questionText.textContent = q.question;

  state.visited.add(idx); // Mark visited

  // Detect "Choose two", "Select 3", "Choose three", etc.
  let mCount = 1;
  const match = /(?:choose|select) (two|three|four|2|3|4)/i.exec(q.question);
  if (match) {
    const val = match[1].toLowerCase();
    if (val === 'two' || val === '2') mCount = 2;
    else if (val === 'three' || val === '3') mCount = 3;
    else if (val === 'four' || val === '4') mCount = 4;
  }
  state.multiCount = mCount;

  // Options
  const grid = document.getElementById('options-grid');
  grid.innerHTML = '';

  const revealed = state.revealedAnswers[q._id];
  const ansArr = state.userAnswers[q._id] || [];

  // Feedback chip
  if (revealed) {
    const chip = document.createElement('div');
    chip.className = `feedback-chip ${revealed.isCorrect ? 'correct-chip' : 'wrong-chip'}`;
    chip.innerHTML = revealed.isCorrect
      ? '✓ Correct!'
      : `✗ Wrong – Correct answer: <strong>${revealed.correct}</strong>`;
    grid.appendChild(chip);
  }

  Object.entries(q.options).forEach(([key, text]) => {
    const btn = document.createElement('button');
    btn.className = 'option-btn';
    btn.id = `opt-${key}`;
    btn.innerHTML = `<span class="option-key">${key}</span><span class="option-text">${escHtml(text)}</span>`;

    if (revealed) {
      btn.disabled = true;
      if (revealed.correct.includes(key)) btn.classList.add('correct');
      else if (ansArr.includes(key) && !revealed.correct.includes(key)) btn.classList.add('wrong');
    } else if (ansArr.includes(key)) {
      btn.classList.add('selected');
    }

    if (!revealed) {
      btn.onclick = () => selectOption(q._id, key);
    }

    grid.appendChild(btn);
  });

  // Nav dots
  renderDots();

  // Buttons
  document.getElementById('btn-prev').disabled = idx === 0;
  const nextBtn = document.getElementById('btn-next');
  const submitBtn = document.getElementById('btn-submit');

  if (idx === total - 1) {
    nextBtn.style.display = 'none';
    submitBtn.style.display = 'flex';
  } else {
    nextBtn.style.display = 'flex';
    submitBtn.style.display = 'none';
  }
}

function renderDots() {
  const nav = document.getElementById('dot-nav');
  nav.innerHTML = state.questions.map((q, i) => {
    let cls = 'dot';
    if (i === state.currentIndex) cls += ' current';
    else if (state.revealedAnswers[q._id]) {
      cls += state.revealedAnswers[q._id].isCorrect ? ' correct-dot' : ' wrong-dot';
    } else if (state.userAnswers[q._id] && state.userAnswers[q._id].length > 0) {
      cls += ' answered';
    } else if (state.visited.has(i)) {
      cls += ' visited';
    }
    return `<div class="${cls}" onclick="goToQuestion(${i})" title="Q${i + 1}">${i + 1}</div>`;
  }).join('');
}

function selectOption(questionId, key) {
  let arr = state.userAnswers[questionId] || [];
  if (arr.includes(key)) {
    arr = arr.filter(k => k !== key); // toggle off
  } else {
    if (arr.length < (state.multiCount || 1)) {
      arr.push(key);
    } else {
      arr.shift();
      arr.push(key); // keep array at max allowed length
    }
  }
  state.userAnswers[questionId] = arr;

  // Visual feedback immediately
  document.querySelectorAll('.option-btn').forEach(b => {
    const k = b.id.replace('opt-', '');
    if (arr.includes(k)) b.classList.add('selected');
    else b.classList.remove('selected');
  });

  // If this is the last question, show the submit button if answered
  if (state.currentIndex === state.questions.length - 1) {
    document.getElementById('btn-submit').style.display = arr.length > 0 ? 'flex' : 'none';
  }

  renderDots();
}

function goToQuestion(i) {
  state.currentIndex = i;
  renderQuestion();
}

function nextQuestion() {
  if (state.currentIndex < state.questions.length - 1) {
    state.currentIndex++;
    renderQuestion();
  }
}

function prevQuestion() {
  if (state.currentIndex > 0) {
    state.currentIndex--;
    renderQuestion();
  }
}

// ── Submit Quiz ────────────────────────────────────────────────
async function submitQuiz(autoSubmit = false) {
  const unanswered = state.questions.filter(q => !state.userAnswers[q._id] || state.userAnswers[q._id].length === 0);
  if (!autoSubmit && unanswered.length > 0) {
    const proceed = confirm(`You have ${unanswered.length} unanswered question(s). Submit anyway?`);
    if (!proceed) return;
  }

  stopTimer();
  const timeTakenSecs = (state.questions.length * 144) - state.timeLeft;
  const timeTaken = formatTime(timeTakenSecs);

  const answers = Object.entries(state.userAnswers).map(([qid, arr]) => ({
    question_id: qid,
    selected_answer: arr.join(',')
  }));

  // Also include unanswered as empty
  state.questions.forEach(q => {
    if (!state.userAnswers[q._id] || state.userAnswers[q._id].length === 0) {
      answers.push({ question_id: q._id, selected_answer: '' });
    }
  });

  document.getElementById('btn-submit').disabled = true;
  document.getElementById('btn-submit').textContent = 'Submitting…';

  try {
    const res = await fetch(`${API}/api/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, answers }),
    });

    if (!res.ok) throw new Error('Submit failed');
    const result = await res.json();

    // Update localStorage
    state.totalQuizzesTaken++;
    localStorage.setItem('certiq_total', state.totalQuizzesTaken.toString());

    showResults(result, timeTaken);
  } catch (err) {
    showToast('⚠️ Submission failed. Check server connection.');
    document.getElementById('btn-submit').disabled = false;
    document.getElementById('btn-submit').textContent = 'Submit Quiz';
  }
}

// ══════════════════════════════════════════════════════════════
// RESULTS SCREEN
// ══════════════════════════════════════════════════════════════
function showResults(result, timeTaken) {
  const { score, total, percentage, details } = result;

  // Badge + title
  let badge = '🎉', title = 'Excellent Work!', subtitle = 'Outstanding performance!';
  if (percentage < 50) { badge = '📚'; title = 'Keep Studying!'; subtitle = 'Review the material and try again.'; }
  else if (percentage < 70) { badge = '📈'; title = 'Good Effort!'; subtitle = 'You\'re on the right track.'; }
  else if (percentage < 85) { badge = '🌟'; title = 'Great Score!'; subtitle = 'Almost there – keep it up!'; }

  document.getElementById('result-badge').textContent = badge;
  document.getElementById('result-title').textContent = title;
  document.getElementById('result-subtitle').textContent = subtitle;

  // Score stats
  document.getElementById('score-pct').textContent = `${percentage}%`;
  document.getElementById('res-correct').textContent = score;
  document.getElementById('res-wrong').textContent = total - score;

  // Calculate physically answered files (array length > 0)
  const answeredCount = Object.values(state.userAnswers).filter(arr => Array.isArray(arr) && arr.length > 0).length;
  document.getElementById('res-answered').textContent = answeredCount;

  document.getElementById('res-total').textContent = total;
  document.getElementById('res-time').textContent = timeTaken;

  // Animate ring: circumference = 2πr = 2π×50 ≈ 314
  const circumference = 314;
  const dashOffset = circumference - (percentage / 100) * circumference;
  setTimeout(() => {
    document.getElementById('score-ring-fill').style.strokeDashoffset = dashOffset;
  }, 100);

  // Breakdown
  const list = document.getElementById('breakdown-list');
  list.innerHTML = details.map((d, i) => `
    <div class="breakdown-item ${d.is_correct ? 'correct-item' : 'wrong-item'}">
      <div class="bi-header">
        <p class="bi-q"><strong>Q${i + 1}.</strong> ${escHtml(d.question)}</p>
        <span class="bi-badge ${d.is_correct ? 'c' : 'w'}">${d.is_correct ? '✓ Correct' : '✗ Wrong'}</span>
      </div>
      <div class="bi-answers">
        ${!d.is_correct ? `<span class="bi-your">Your answer: <span>${d.selected_answer || 'Skipped'}</span></span>` : ''}
        <span class="bi-correct-lbl">Correct: <span>${d.correct_answer}</span></span>
      </div>
      ${d.explanation ? `<p class="bi-explanation">${escHtml(d.explanation)}</p>` : ''}
      <span class="bi-topic">${escHtml(d.topic || 'General')}</span>
    </div>`).join('');

  showScreen('results');
}

// ══════════════════════════════════════════════════════════════
// TIMER
// ══════════════════════════════════════════════════════════════
function startTimer() {
  stopTimer();
  updateTimerDisplay();
  state.timerInterval = setInterval(() => {
    state.timeLeft--;
    updateTimerDisplay();
    if (state.timeLeft <= 0) {
      stopTimer();
      showToast("Time's up! Auto-submitting...");
      submitQuiz(true);
    }
  }, 1000);
}

function stopTimer() {
  if (state.timerInterval) {
    clearInterval(state.timerInterval);
    state.timerInterval = null;
  }
}

function updateTimerDisplay() {
  document.getElementById('timer').textContent = formatTime(state.timeLeft);
}

function formatTime(secs) {
  if (secs < 0) secs = 0;
  const h = Math.floor(secs / 3600);
  const m = String(Math.floor((secs % 3600) / 60)).padStart(2, '0');
  const s = String(secs % 60).padStart(2, '0');
  return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
}

// ══════════════════════════════════════════════════════════════
// SCREEN MANAGEMENT
// ══════════════════════════════════════════════════════════════
function showScreen(name) {
  Object.values(screens).forEach(s => {
    s.style.display = 'none';
    s.classList.remove('active', 'fade-in');
  });
  const target = screens[name];
  target.style.display = 'block';
  target.classList.add('active', 'fade-in');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showHome() {
  stopTimer();
  closeModal();
  // Refresh stats
  loadStats();
  document.getElementById('stat-taken').textContent = state.totalQuizzesTaken;
  // Reset ring for next result
  document.getElementById('score-ring-fill').style.strokeDashoffset = '314';
  showScreen('home');
}

// ── Exit Modal ─────────────────────────────────────────────────
function confirmExit() {
  document.getElementById('exit-modal').style.display = 'flex';
}
function closeModal() {
  document.getElementById('exit-modal').style.display = 'none';
}
document.getElementById('exit-modal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) closeModal();
});

// ── Toast ──────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
}

// ── Utilities ──────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function animateNumber(id, target) {
  const el = document.getElementById(id);
  if (!el || !target) { if (el) el.textContent = target || 0; return; }
  let current = 0;
  const step = Math.ceil(target / 40);
  const interval = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(interval);
  }, 30);
}

// ── Boot ───────────────────────────────────────────────────────
init();
