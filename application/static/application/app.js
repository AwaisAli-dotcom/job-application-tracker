document.querySelectorAll('.form-field input, .form-field select, .form-field textarea').forEach(function (field) {
    field.addEventListener('input', clearFieldError);
    field.addEventListener('change', clearFieldError);
});

function clearFieldError(event) {
    var fieldWrapper = event.target.closest('.form-field');
    var errorList = fieldWrapper ? fieldWrapper.querySelector('.errorlist') : null;

    if (errorList) {
        errorList.remove();
    }

    event.target.removeAttribute('aria-invalid');
}
