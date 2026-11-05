/**
 * MyFam - Authentication & PIN Verification Script
 * Separated JavaScript for index.html
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const authView = document.getElementById('auth-view');
    const starsView = document.getElementById('stars-view');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const pinForm = document.getElementById('pin-form');
    const authMessage = document.getElementById('auth-message');
    const pinMessage = document.getElementById('pin-message');
    const welcomeUsernameSpan = document.getElementById('welcome-username');
    const showLoginBtn = document.getElementById('show-login');
    const showRegisterBtn = document.getElementById('show-register');
    const backToLoginBtn = document.getElementById('back-to-login');

    // Message helpers
    function showMessage(message, type) {
        if (!authMessage) return;
        authMessage.textContent = message;
        authMessage.className = `message ${type || ''}`;
    }

    function showPinMessage(message, type) {
        if (!pinMessage) return;
        pinMessage.textContent = message;
        pinMessage.className = `message ${type || ''}`;
    }

    // View switchers
    function showLogin() {
        if (authView) authView.hidden = false;
        if (loginForm) loginForm.hidden = false;
        if (registerForm) registerForm.hidden = true;
        if (starsView) {
            starsView.hidden = true;
            starsView.setAttribute('aria-hidden', 'true');
        }
        if (showLoginBtn) showLoginBtn.setAttribute('aria-selected', 'true');
        if (showRegisterBtn) showRegisterBtn.setAttribute('aria-selected', 'false');
        showMessage('', '');
    }

    function showRegister() {
        if (authView) authView.hidden = false;
        if (loginForm) loginForm.hidden = true;
        if (registerForm) registerForm.hidden = false;
        if (starsView) {
            starsView.hidden = true;
            starsView.setAttribute('aria-hidden', 'true');
        }
        if (showLoginBtn) showLoginBtn.setAttribute('aria-selected', 'false');
        if (showRegisterBtn) showRegisterBtn.setAttribute('aria-selected', 'true');
        showMessage('', '');
    }

    function showStars(username) {
        if (authView) authView.hidden = true;
        if (starsView) {
            starsView.hidden = false;
            starsView.setAttribute('aria-hidden', 'false');
        }
        if (welcomeUsernameSpan) {
            welcomeUsernameSpan.textContent = username;
        }
        if (pinForm) {
            pinForm.reset();
            const pinInput = pinForm.querySelector('input[name="pin"]');
            if (pinInput) pinInput.focus();
        }
        showPinMessage('', '');
    }

    // CSRF Token fetcher
    async function getCsrfToken() {
        const response = await fetch('/api/csrf');
        const data = await response.json();
        if (!response.ok || !data.csrf_token) {
            throw new Error('Unable to verify request security token. Please refresh and try again.');
        }
        return data.csrf_token;
    }

    // Event Handlers
    if (showLoginBtn) showLoginBtn.addEventListener('click', showLogin);
    if (showRegisterBtn) showRegisterBtn.addEventListener('click', showRegister);
    if (backToLoginBtn) backToLoginBtn.addEventListener('click', showLogin);

    // 1. Password Login Submission
    if (loginForm) {
        loginForm.addEventListener('submit', async event => {
            event.preventDefault();
            const username = loginForm.elements.username.value.trim();
            const password = loginForm.elements.password.value;

            if (!username || !password) {
                showMessage('Please enter both username and password.', 'error');
                return;
            }

            try {
                const csrfToken = await getCsrfToken();
                const response = await fetch('/api/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json();
                if (!response.ok) {
                    showMessage(data.error || 'Invalid username or password.', 'error');
                    return;
                }

                // Password verified! Transition directly to the stars view for PIN entry
                showStars(username);
            } catch (err) {
                showMessage('Network error. Please try again.', 'error');
            }
        });
    }

    // 2. PIN Verification Submission
    if (pinForm) {
        pinForm.addEventListener('submit', async event => {
            event.preventDefault();
            const pin = pinForm.elements.pin.value.trim();

            if (!pin || pin.length !== 4) {
                showPinMessage('Please enter a valid 4-digit PIN.', 'error');
                return;
            }

            try {
                const csrfToken = await getCsrfToken();
                const response = await fetch('/api/pin', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    body: JSON.stringify({ pin })
                });

                const data = await response.json();
                if (!response.ok) {
                    showPinMessage(data.error || 'Incorrect PIN. Please try again.', 'error');
                    return;
                }

                // PIN is correct! Let user into the site
                showPinMessage('PIN verified. Entering portal...', 'success');
                setTimeout(() => {
                    window.location.assign('/welcome');
                }, 400);
            } catch (err) {
                showPinMessage('Network error. Please try again.', 'error');
            }
        });
    }

    // 3. User Registration Submission
    if (registerForm) {
        registerForm.addEventListener('submit', async event => {
            event.preventDefault();
            const username = registerForm.elements.username.value.trim();
            const password = registerForm.elements.password.value;
            const pin = registerForm.elements.pin.value.trim();

            try {
                const csrfToken = await getCsrfToken();
                const response = await fetch('/api/register', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': csrfToken
                    },
                    body: JSON.stringify({ username, password, pin })
                });

                const data = await response.json();
                if (!response.ok) {
                    showMessage(data.error || 'Request failed. Please try again.', 'error');
                    return;
                }

                // Switch to login tab and prefill username
                loginForm.elements.username.value = username;
                showLogin();
                showMessage('Account created successfully! Please log in.', 'success');
            } catch (err) {
                showMessage('Network error. Please try again.', 'error');
            }
        });
    }
});

