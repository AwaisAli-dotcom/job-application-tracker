document.querySelectorAll('.form-field input, .form-field select, .form-field textarea').forEach(function (field) {
    field.addEventListener('input', clearFieldError);
    field.addEventListener('change', clearFieldError);
});

function clearFieldError(event) {
    var fieldWrapper = event.target.closest('.form-field');
    var errorList = fieldWrapper ? fieldWrapper.querySelector('.errorlist') : null;

    if (errorList) {
        var errorId = errorList.id;
        var describedBy = event.target.getAttribute('aria-describedby');

        if (errorId && describedBy) {
            var remaining = describedBy.split(/\s+/).filter(function (id) {
                return id !== errorId;
            });

            if (remaining.length) {
                event.target.setAttribute('aria-describedby', remaining.join(' '));
            } else {
                event.target.removeAttribute('aria-describedby');
            }
        }

        errorList.remove();
    }

    event.target.removeAttribute('aria-invalid');
}

(function initializeApplicationNavigation() {
    var toggle = document.querySelector('[data-nav-toggle]');
    var sidebar = document.querySelector('[data-app-sidebar]');
    var overlay = document.querySelector('[data-nav-overlay]');

    if (!toggle || !sidebar || !overlay) {
        return;
    }

    var mobileQuery = window.matchMedia('(max-width: 860px)');

    function setNavigationOpen(open, returnFocus) {
        var shouldOpen = mobileQuery.matches && open;

        sidebar.classList.toggle('is-open', shouldOpen);
        document.body.classList.toggle('navigation-open', shouldOpen);
        toggle.setAttribute('aria-expanded', String(shouldOpen));
        toggle.setAttribute('aria-label', shouldOpen ? 'Close navigation' : 'Open navigation');
        overlay.hidden = !shouldOpen;

        if (mobileQuery.matches && !shouldOpen) {
            sidebar.setAttribute('inert', '');
        } else {
            sidebar.removeAttribute('inert');
        }

        if (shouldOpen) {
            var focusDelay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 200;

            window.setTimeout(function () {
                if (sidebar.classList.contains('is-open')) {
                    sidebar.querySelector('.sidebar-primary-action').focus();
                }
            }, focusDelay);
        } else if (returnFocus) {
            toggle.focus();
        }
    }

    toggle.addEventListener('click', function () {
        setNavigationOpen(toggle.getAttribute('aria-expanded') !== 'true', false);
    });

    overlay.addEventListener('click', function () {
        setNavigationOpen(false, true);
    });

    sidebar.querySelectorAll('a').forEach(function (link) {
        link.addEventListener('click', function () {
            if (mobileQuery.matches) {
                setNavigationOpen(false, false);
            }
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
            setNavigationOpen(false, true);
        }
    });

    mobileQuery.addEventListener('change', function () {
        setNavigationOpen(false, false);
    });

    setNavigationOpen(false, false);
}());

document.querySelectorAll('.account-menu').forEach(function (menu) {
    document.addEventListener('click', function (event) {
        if (menu.open && !menu.contains(event.target)) {
            menu.removeAttribute('open');
        }
    });

    menu.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            menu.removeAttribute('open');
            menu.querySelector('summary').focus();
        }
    });
});

document.querySelectorAll('[data-upload-zone]').forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var filename = zone.querySelector('[data-file-name]');

    if (!input || !filename) {
        return;
    }

    function showSelectedFile() {
        filename.textContent = input.files.length ? input.files[0].name : 'No file selected';
    }

    input.addEventListener('change', showSelectedFile);

    ['dragenter', 'dragover'].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
            event.preventDefault();
            zone.classList.add('is-dragover');
        });
    });

    ['dragleave', 'drop'].forEach(function (eventName) {
        zone.addEventListener(eventName, function (event) {
            event.preventDefault();
            zone.classList.remove('is-dragover');
        });
    });

    zone.addEventListener('drop', function (event) {
        if (!event.dataTransfer.files.length) {
            return;
        }

        var transfer = new DataTransfer();
        transfer.items.add(event.dataTransfer.files[0]);
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', {bubbles: true}));
    });
});
