(() => {
  const script = document.currentScript;
  if (!script) return;

  const csrf = () => {
    const item = document.cookie.split('; ').find((value) => value.startsWith('csrftoken='));
    return item ? decodeURIComponent(item.slice('csrftoken='.length)) : '';
  };
  const post = (url, data = {}) => fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'X-CSRFToken': csrf(),
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
    },
    body: new URLSearchParams(data),
  }).then((response) => response.ok ? response.json() : null);

  let sessionToken = null;
  let inFlight = false;
  const heartbeat = () => {
    if (!sessionToken || inFlight || document.visibilityState !== 'visible' || !document.hasFocus()) return;
    inFlight = true;
    post(script.dataset.heartbeatUrl, { session_token: sessionToken })
      .then((result) => {
        if (!result) return;
        if (result.complete) sessionToken = null;
        if (result.awarded) {
          let status = document.getElementById('website-engagement-status');
          if (!status) {
            status = document.createElement('div');
            status.id = 'website-engagement-status';
            status.className = 'alert alert-success container mt-3';
            document.querySelector('main')?.prepend(status);
          }
          status.textContent = result.milestone_completed
            ? '🔥 30 Day Streak Completed · Today’s Website Coin added.'
            : 'Today’s Website Coin has been added to your wallet.';
          window.dispatchEvent(new CustomEvent('shopcoin:website-coin-awarded', { detail: result }));
          window.setTimeout(() => window.location.reload(), 1200);
        }
      })
      .catch(() => {})
      .finally(() => { inFlight = false; });
  };
  post(script.dataset.startUrl).then((result) => {
    if (!result || !result.eligible || result.complete) return;
    sessionToken = result.session_token;
    heartbeat();
  }).catch(() => {});

  window.setInterval(heartbeat, 15000);
})();
