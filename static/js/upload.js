(() => {
  'use strict';
  const form = document.getElementById('upload-form');
  const dateInput = document.getElementById('up-date');
  document.querySelectorAll('[data-shift]').forEach(button => button.addEventListener('click', () => {
    const date = new Date();
    date.setDate(date.getDate() + Number(button.dataset.shift));
    dateInput.value = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  }));
  const boxes = Array.from(document.querySelectorAll('#up-branches input'));
  function validateBranches() {
    if (boxes.length) boxes[0].setCustomValidity(boxes.some(box => box.checked) ? '' : 'Выберите хотя бы один филиал.');
  }
  boxes.forEach(box => box.addEventListener('change', validateBranches));
  document.getElementById('up-ball').addEventListener('click', () => { boxes.forEach(box => { box.checked = true; }); validateBranches(); });
  document.getElementById('up-bnone').addEventListener('click', () => { boxes.forEach(box => { box.checked = false; }); validateBranches(); });
  validateBranches();
  form.addEventListener('submit', () => {
    const button = form.querySelector('[type="submit"]');
    button.disabled = true; button.textContent = 'Публикуем…'; form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    const button = form.querySelector('[type="submit"]');
    button.disabled = false; button.textContent = 'Опубликовать расписание'; form.removeAttribute('aria-busy');
  });
  document.getElementById('hist-month').addEventListener('change', () => document.getElementById('hist-form').requestSubmit());
})();
