import {encodeServicePassword} from '../utils.js';

export function setupUpload() {
  const dialog = document.querySelector('#upload-dialog');
  const openButton = document.querySelector('#open-upload');
  const closeButton = document.querySelector('#upload-close');
  const form = document.querySelector('#upload-form');
  const file = document.querySelector('#upload-file');
  const password = document.querySelector('#upload-password');
  const status = document.querySelector('#upload-status');
  const button = document.querySelector('#upload-submit');
  openButton.addEventListener('click', () => {
    status.textContent = '';
    status.classList.remove('error');
    dialog.showModal();
  });
  closeButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => {
    if (button.disabled) event.preventDefault();
  });
  dialog.addEventListener('close', () => form.reset());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled || !file.files.length || !password.value) return;
    button.disabled = true;
    closeButton.disabled = true;
    status.textContent = '正在上传…';
    status.classList.remove('error');
    try {
      const response = await fetch('/api/upload-paper', {
        method:'POST', headers:{'Content-Type':'application/pdf', 'X-Service-Password':encodeServicePassword(password.value),
          'X-Filename':encodeURIComponent(file.files[0].name), 'X-Process-Paper':'true'}, body:file.files[0],
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '上传失败');
      status.textContent = result.task_id
        ? `上传成功。可在「任务状态」中查看 ${result.task_id}。`
        : '上传成功，文件已保存至待处理目录。';
      form.reset();
    } catch (error) {
      status.textContent = error.message || '上传失败';
      status.classList.add('error');
    } finally {
      password.value = '';
      button.disabled = false;
      closeButton.disabled = false;
    }
  });
}
