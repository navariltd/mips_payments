document.addEventListener('DOMContentLoaded', function () {
    const statusCode = parseInt({{ fetch_code|safe }});

    if (statusCode === 200){
        const loadingAnimation = document.querySelector('.lds-dual-ring');

        if (loadingAnimation) {
            loadingAnimation.classList.remove('lds-dual-ring');
            const target = String({{ redirect_to|safe }});
            window.location.href = target;
        }
    } else {
        alert("Fetch failed")
    }
});
