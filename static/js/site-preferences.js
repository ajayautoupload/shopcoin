(() => {
  let translations = {};
  const languageApi = '/preferences/language/';
  const catalogueApi = '/preferences/translations/';
  const pageLanguage = document.documentElement.lang;
  const savedLanguage = ['en', 'hi'].includes(pageLanguage)
    ? pageLanguage
    : (localStorage.getItem('shopcoin-language') || 'en');
  const savedTheme = localStorage.getItem('shopcoin-theme') || 'light';
  const translatableAttributes = ['placeholder', 'title', 'aria-label', 'alt'];

  function translateValue(value, language) {
    if (language !== 'hi') return value;
    if (translations[value] !== undefined) return translations[value];
    const patterns = [
      [/^Bill (.+) was generated successfully\.$/, 'बिल $1 सफलतापूर्वक बनाया गया।'],
      [/^Payment ₹(.+) recorded\.$/, '₹$1 का भुगतान दर्ज किया गया।'],
      [/^(.+) was added to your products\.$/, '$1 आपके उत्पादों में जोड़ दिया गया।'],
      [/^(.+) was updated\.$/, '$1 अपडेट किया गया।'],
      [/^(.+) was deleted\.$/, '$1 हटा दिया गया।'],
      [/^(.+) was created\.$/, '$1 बनाया गया।'],
      [/^(.+) is now active\.$/, '$1 अब सक्रिय है।'],
      [/^(.+) is now inactive\.$/, '$1 अब निष्क्रिय है।'],
      [/^₹(.+) remaining$/, '₹$1 बाकी'],
      [/^Hello, (.+)$/, 'नमस्ते, $1'],
      [/^Create bill for (.+)$/, '$1 के लिए बिल बनाएँ'],
      [/^Available at (.+)$/, 'यहाँ उपलब्ध: $1'],
      [/^New styles from (.+) will appear here\.$/, '$1 के नए उत्पाद यहाँ दिखेंगे।'],
      [/^(.+) offers will appear here\.$/, '$1 के ऑफ़र यहाँ दिखेंगे।'],
      [/^Coins earned: (.+) · Wallet now (.+) coins$/, 'कमाए कॉइन: $1 · वॉलेट में अभी $2 कॉइन'],
      [/^Total Reward Value ₹([0-9,.]+)$/, 'कुल इनाम मूल्य ₹$1'],
      [/^Worth ₹([0-9,.]+)$/, 'मूल्य ₹$1'],
      [/^Current streak: (\d+) days?$/, 'वर्तमान सिलसिला: $1 दिन'],
      [/^Longest streak: (\d+) days?$/, 'सबसे लंबा सिलसिला: $1 दिन'],
      [/^(\d+) coins redeemed for ₹(.+)\.$/, '₹$2 के $1 कॉइन रिडीम हुए।'],
      [/^Add Customer · (.+)$/, 'ग्राहक जोड़ें · $1'],
      [/^Customers · (.+)$/, 'ग्राहक · $1'],
      [/^(.+) customers, including deleted accounts\.$/, '$1 ग्राहक, हटाए गए खातों सहित।'],
      [/^Bill total ₹([0-9,.]+)$/, 'बिल की कुल राशि ₹$1'],
      [/^Total ₹([0-9,.]+)$/, 'कुल ₹$1'],
      [/^Payment amount \(maximum ₹([0-9,.]+)\)$/, 'भुगतान राशि (अधिकतम ₹$1)'],
      [/^Request (\d+) Coins · ₹([0-9,.]+)$/, '$1 कॉइन का अनुरोध · ₹$2'],
      [/^Website Coins: (\d+)\/100 · Qualifying Bills: (\d+)\/3$/, 'वेबसाइट कॉइन: $1/100 · योग्य बिल: $2/3'],
      [/^Current streak: (\d+) days · Longest streak: (\d+) days · Total Website Coins earned: (\d+)$/, 'वर्तमान सिलसिला: $1 दिन · सबसे लंबा सिलसिला: $2 दिन · कुल कमाए वेबसाइट कॉइन: $3'],
      [/^Delete (.+)\?$/, '$1 हटाएँ?'],
      [/^© (\d{4}) Shop Coin$/, '© $1 शॉप कॉइन'],
      [/^· Application (.+)$/, '· आवेदन $1'],
    ];
    for (const [pattern, replacement] of patterns) {
      if (pattern.test(value)) return value.replace(pattern, replacement);
    }
    return value;
  }

  function translateTextNode(node, language) {
    if (!node.parentElement || /^(SCRIPT|STYLE|NOSCRIPT)$/.test(node.parentElement.tagName)) return;
    if (node.dataset.originalText === undefined) node.dataset.originalText = node.nodeValue;
    const original = node.parentElement.dataset.i18nKey || node.dataset.originalText;
    const trimmed = original.trim();
    if (!trimmed) return;
    const translated = translateValue(trimmed, language);
    const nextValue = original.replace(trimmed, translated);
    if (node.nodeValue !== nextValue) node.nodeValue = nextValue;
  }

  function translateElement(element, language) {
    if (element.nodeType === Node.TEXT_NODE) {
      translateTextNode(element, language);
      return;
    }
    if (!(element instanceof Element)) return;
    if (element.matches('script,style,noscript')) return;
    for (const attribute of translatableAttributes) {
      if (!element.hasAttribute(attribute)) continue;
      const originalName = `original${attribute.replace(/(^|-)(.)/g, (_, __, letter) => letter.toUpperCase())}`;
      const markedOriginal = element.dataset[`i18nAttr${attribute.replace(/(^|-)(.)/g, (_, __, letter) => letter.toUpperCase())}`];
      if (markedOriginal !== undefined) element.dataset[originalName] = markedOriginal;
      if (element.dataset[originalName] === undefined) element.dataset[originalName] = element.getAttribute(attribute);
      const translated = translateValue(element.dataset[originalName], language);
      if (element.getAttribute(attribute) !== translated) element.setAttribute(attribute, translated);
    }
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => translateTextNode(node, language));
  }

  function applyLanguage(language) {
    document.documentElement.lang = language;
    document.querySelectorAll('[data-language-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.languageChoice === language));
    });
    translateElement(document.body, language);
  }

  function loadCatalogue(language) {
    return fetch(`${catalogueApi}?language=${encodeURIComponent(language)}`, {credentials: 'same-origin'})
      .then(response => response.ok ? response.json() : {})
      .then(catalogue => { translations = catalogue; applyLanguage(language); })
      .catch(() => { translations = {}; applyLanguage(language); });
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
    });
  }

  document.addEventListener('click', event => {
    const languageButton = event.target.closest('[data-language-choice]');
    if (languageButton) {
      const language = languageButton.dataset.languageChoice;
      localStorage.setItem('shopcoin-language', language);
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
      fetch(languageApi, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf || ''},
        body: new URLSearchParams({language}),
      }).catch(() => {});
      loadCatalogue(language);
    }
    const themeButton = event.target.closest('[data-theme-choice]');
    if (themeButton) {
      localStorage.setItem('shopcoin-theme', themeButton.dataset.themeChoice);
      applyTheme(themeButton.dataset.themeChoice);
    }
  });

  new MutationObserver(records => {
    for (const record of records) {
      record.addedNodes.forEach(node => translateElement(node, document.documentElement.lang || savedLanguage));
      if (record.type === 'characterData') translateTextNode(record.target, document.documentElement.lang || savedLanguage);
    }
  }).observe(document.body, {childList: true, subtree: true, characterData: true});

  applyTheme(savedTheme);
  loadCatalogue(savedLanguage);
})();
