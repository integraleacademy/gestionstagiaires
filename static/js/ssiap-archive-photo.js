(() => {
  const input = document.getElementById('sr-upload');
  const preview = document.getElementById('sr-portrait');
  const original = preview.getAttribute('src');
  let previous;
  input.addEventListener('change', () => {
    if (previous) URL.revokeObjectURL(previous);
    previous = input.files[0] ? URL.createObjectURL(input.files[0]) : null;
    preview.hidden = !previous && !original;
    if (previous || original) preview.src = previous || original;
    else preview.removeAttribute('src');
  });
})();
