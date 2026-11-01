document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form').forEach((form) => {
    form.querySelectorAll('input:not([type=hidden]), textarea, select').forEach((field) => {
      if (field.type === 'checkbox') field.classList.add('form-check-input');
      if (!field.classList.contains('form-control') && field.type !== 'checkbox' && field.type !== 'file') {
        field.classList.add('form-control');
      }
      if (field.type === 'file') field.classList.add('form-control');
    });
  });

  document.querySelectorAll('img[data-fallback]').forEach((image) => {
    const useFallback = () => {
      image.src = image.dataset.fallback;
      image.removeAttribute('data-fallback');
    };
    image.addEventListener('error', useFallback, { once: true });
    if (image.complete && image.naturalWidth === 0) useFallback();
  });
});
