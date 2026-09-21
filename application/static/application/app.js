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
