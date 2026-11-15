(() => {
  const translations = {
    'Shop Coin': 'शॉप कॉइन', 'Shopkeeper Login': 'दुकानदार लॉगिन', 'Customer Login': 'ग्राहक लॉगिन',
    'Customer login': 'ग्राहक लॉगिन', 'Register your shop': 'अपनी दुकान रजिस्टर करें',
    'Home': 'होम', 'Shop': 'दुकान', 'Wallet': 'वॉलेट', 'Coin Rules': 'कॉइन नियम',
    'Profile': 'प्रोफ़ाइल', 'Dashboard': 'डैशबोर्ड', 'Products': 'उत्पाद', 'Customers': 'ग्राहक',
    'Orders': 'ऑर्डर', 'Sales': 'बिक्री', 'Log out': 'लॉग आउट', 'Sign out': 'साइन आउट',
    'Language & theme': 'भाषा और थीम', 'Language': 'भाषा', 'Theme': 'थीम', 'English': 'अंग्रेज़ी',
    'हिन्दी': 'हिन्दी', 'Light': 'लाइट', 'Dark': 'डार्क', 'Earn Coins.': 'कॉइन कमाएँ।',
    'Save More.': 'ज़्यादा बचाएँ।', 'A smarter way to shop': 'खरीदारी का बेहतर तरीका',
    'Shop from local businesses, earn Shop Coins, and': 'स्थानीय दुकानों से खरीदारी करें, शॉप कॉइन कमाएँ और',
    'enjoy rewards on your purchases.': 'अपनी खरीदारी पर इनाम पाएँ।',
    'Shop Coin connects customers with local shops through a simple rewards': 'शॉप कॉइन ग्राहकों को स्थानीय दुकानों से जोड़ता है और',
    'system that makes everyday shopping more rewarding.': 'रोज़ की खरीदारी पर इनाम देता है।',
    'Register as a shopkeeper': 'दुकानदार के रूप में रजिस्टर करें', 'First name': 'पहला नाम',
    'Last name': 'उपनाम', 'Email': 'ईमेल', 'Phone': 'फ़ोन', 'Business name': 'व्यवसाय का नाम',
    'Password': 'पासवर्ड', 'Confirm password': 'पासवर्ड की पुष्टि करें',
    'Start earning more from local shopping.': 'स्थानीय खरीदारी से अधिक कमाई शुरू करें।',
    'Create Shopkeeper account': 'दुकानदार खाता बनाएँ', 'Already have an account?': 'पहले से खाता है?',
    'Log in': 'लॉग इन', 'Add Product': 'उत्पाद जोड़ें', 'Save Product': 'उत्पाद सेव करें',
    'My Products': 'मेरे उत्पाद', 'Manage products': 'उत्पाद प्रबंधित करें',
    'Create bill': 'बिल बनाएँ', 'Create Bill': 'बिल बनाएँ', 'Generate Bill': 'बिल बनाएँ',
    'Cancel': 'रद्द करें', 'Search': 'खोजें', 'Create Udhar': 'उधार दर्ज करें',
    'Udhar / Credit': 'उधार', 'Customer': 'ग्राहक', 'Quantity': 'मात्रा',
    'Product name': 'उत्पाद का नाम', 'Price (₹)': 'कीमत (₹)', 'Subtotal': 'उप-योग',
    'Final amount': 'अंतिम राशि', 'Discount (₹)': 'छूट (₹)', 'Description': 'विवरण',
    'Due date': 'देय तिथि', 'Reference': 'संदर्भ', 'Existing bill (optional)': 'मौजूदा बिल (वैकल्पिक)',
    'Active': 'सक्रिय', 'Inactive': 'निष्क्रिय', 'Is new': 'नया उत्पाद', 'Stock': 'स्टॉक',
    'Name not provided': 'नाम उपलब्ध नहीं', 'Owner': 'मालिक'
  };
  const savedLanguage = localStorage.getItem('shopcoin-language') || 'en';
  const savedTheme = localStorage.getItem('shopcoin-theme') || 'light';

  function applyLanguage(language) {
    document.documentElement.lang = language;
    document.querySelectorAll('[data-language-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.languageChoice === language));
    });
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    textNodes.forEach(node => {
      if (!node.parentElement || /^(SCRIPT|STYLE)$/.test(node.parentElement.tagName)) return;
      if (node.dataset.originalText === undefined) node.dataset.originalText = node.nodeValue;
      const original = node.dataset.originalText;
      const trimmed = original.trim();
      if (!trimmed) return;
      const translated = language === 'hi' ? (translations[trimmed] || trimmed) : trimmed;
      node.nodeValue = original.replace(trimmed, translated);
    });
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
      localStorage.setItem('shopcoin-language', languageButton.dataset.languageChoice);
      applyLanguage(languageButton.dataset.languageChoice);
    }
    const themeButton = event.target.closest('[data-theme-choice]');
    if (themeButton) {
      localStorage.setItem('shopcoin-theme', themeButton.dataset.themeChoice);
      applyTheme(themeButton.dataset.themeChoice);
    }
  });

  applyTheme(savedTheme);
  applyLanguage(savedLanguage);
})();
