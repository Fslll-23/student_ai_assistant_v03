'use strict';
// Nicknames stay in this browser only; they are never added to AI requests.
const NICKNAME_KEY = 'baobao_user_nickname';
const normalizeNickname = value => typeof value === 'string' ? value.trim().replace(/[\p{Cc}\p{Cf}]/gu, '') : '';
let currentNickname = '';
function nicknameMessage(id, zh, en) { $(id).textContent = translate(zh, en); }
function displayNickname(name) {
  currentNickname = name;
  $('greeting-nickname').textContent = name;
  $('greeting-nickname').title = name;
  $('nickname-edit').value = name;
}
function saveNickname(input, message) {
  const name = normalizeNickname(input.value);
  if (!name || Array.from(name).length > 16) {
    nicknameMessage(message, !name ? '请输入你的名字或昵称' : '昵称最多 16 个字符哦', !name ? 'Please enter your name or nickname.' : 'Please use at most 16 characters.');
    input.setAttribute('aria-invalid', 'true'); input.focus(); return false;
  }
  try { localStorage.setItem(NICKNAME_KEY, name); }
  catch {
    nicknameMessage(message, '浏览器暂时无法保存，请允许本地存储后重试。', 'Local storage is unavailable. Please enable it and try again.');
    return false;
  }
  input.removeAttribute('aria-invalid'); input.value = name;
  displayNickname(name);
  return true;
}
function showProfileRoute() {
  const profile = location.hash === '#profile';
  $('home-content').classList.toggle('hidden', profile);
  $('profile-page').classList.toggle('hidden', !profile);
  if (profile) {
    $('nickname-edit').value = currentNickname;
    $('nickname-edit-message').textContent = '';
    $('profile-entry').setAttribute('aria-current', 'page');
  } else $('profile-entry').removeAttribute('aria-current');
}
$('nickname-start-form').addEventListener('submit', event => {
  event.preventDefault();
  if (saveNickname($('nickname-start'), 'nickname-start-message')) {
    $('nickname-welcome').close(); location.hash = 'home'; showProfileRoute();
  }
});
$('nickname-edit-form').addEventListener('submit', event => {
  event.preventDefault();
  if (saveNickname($('nickname-edit'), 'nickname-edit-message')) nicknameMessage('nickname-edit-message', '已保存，首页昵称已更新 ✓', 'Saved. Your home greeting is updated ✓');
});
$('nickname-welcome').addEventListener('cancel', event => event.preventDefault());
window.addEventListener('hashchange', showProfileRoute);
// First visit: no valid stored nickname means the welcome card must be completed.
try {
  const stored = normalizeNickname(localStorage.getItem(NICKNAME_KEY));
  if (stored && Array.from(stored).length <= 16) displayNickname(stored);
} catch { /* The form explains unavailable storage when saving. */ }
showProfileRoute();
if (!currentNickname) $('nickname-welcome').showModal();
