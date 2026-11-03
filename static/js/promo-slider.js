document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-promo-slider]').forEach((slider) => {
    const slides = Array.from(slider.querySelectorAll('[data-promo-slide]'));
    const dots = Array.from(slider.querySelectorAll('[data-promo-dot]'));
    if (slides.length < 2) return;

    let activeIndex = slides.findIndex((slide) => slide.classList.contains('is-active'));
    let timer = null;
    let touchStartX = null;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function showSlide(index) {
      activeIndex = (index + slides.length) % slides.length;
      slides.forEach((slide, slideIndex) => {
        const active = slideIndex === activeIndex;
        slide.classList.toggle('is-active', active);
        slide.setAttribute('aria-hidden', String(!active));
      });
      dots.forEach((dot, dotIndex) => {
        const active = dotIndex === activeIndex;
        dot.classList.toggle('is-active', active);
        dot.setAttribute('aria-current', String(active));
      });
    }

    function stopAutoplay() {
      if (timer) window.clearInterval(timer);
      timer = null;
    }

    function startAutoplay() {
      stopAutoplay();
      if (!reducedMotion && !document.hidden) {
        timer = window.setInterval(() => showSlide(activeIndex + 1), 4500);
      }
    }

    slider.querySelector('[data-promo-previous]')?.addEventListener('click', () => {
      showSlide(activeIndex - 1);
      startAutoplay();
    });
    slider.querySelector('[data-promo-next]')?.addEventListener('click', () => {
      showSlide(activeIndex + 1);
      startAutoplay();
    });
    dots.forEach((dot) => dot.addEventListener('click', () => {
      showSlide(Number(dot.dataset.promoDot));
      startAutoplay();
    }));

    slider.addEventListener('mouseenter', stopAutoplay);
    slider.addEventListener('mouseleave', startAutoplay);
    slider.addEventListener('focusin', stopAutoplay);
    slider.addEventListener('focusout', (event) => {
      if (!slider.contains(event.relatedTarget)) startAutoplay();
    });
    slider.addEventListener('touchstart', (event) => {
      touchStartX = event.changedTouches[0].clientX;
      stopAutoplay();
    }, { passive: true });
    slider.addEventListener('touchend', (event) => {
      if (touchStartX === null) return;
      const delta = event.changedTouches[0].clientX - touchStartX;
      touchStartX = null;
      if (Math.abs(delta) > 40) showSlide(activeIndex + (delta < 0 ? 1 : -1));
      startAutoplay();
    }, { passive: true });
    document.addEventListener('visibilitychange', startAutoplay);

    showSlide(activeIndex < 0 ? 0 : activeIndex);
    startAutoplay();
  });
});
