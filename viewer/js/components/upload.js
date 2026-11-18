export function setupUpload() {
  const form = document.querySelector('#upload-form');
  const file = document.querySelector('#upload-file');
  const password = document.querySelector('#upload-password');
  const status = document.querySelector('#upload-status');
  const button = form.querySelector('button');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!file.files.length || !password.value) return;
    button.disabled = true;
    status.textContent = '正在上传…';
    status.classList.remove('error');
    try {
      const bytes = new TextEncoder().encode(password.value);
      const encoded = btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(''));
      const response = await fetch('/api/upload-paper', {
        method:'POST', headers:{'Content-Type':'application/pdf', 'X-Service-Password':encoded,
          'X-Filename':encodeURIComponent(file.files[0].name)}, body:file.files[0],
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '上传失败');
      status.textContent = '上传成功，文件已保存至待处理目录。';
      form.reset();
    } catch (error) {
      status.textContent = error.message || '上传失败';
      status.classList.add('error');
    } finally {
      password.value = '';
      button.disabled = false;
    }
  });
}
