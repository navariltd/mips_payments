document.addEventListener('DOMContentLoaded', function () {
  const statusCode = parseInt('{{ fetch_code|safe }}');
  const status = '{{ status|safe }}';

  const loadingAnimation = document.querySelector('.lds-dual-ring');

  if (statusCode === 200 && status === 'success') {
    if (loadingAnimation) {
      loadingAnimation.classList.remove('lds-dual-ring');
      const target = '{{ redirect_to|safe }}';
      window.location.href = target; // Redirect to target page
    }
  } else if (status === 'error') {
    loadingAnimation.classList.remove('lds-dual-ring');
  } else {
    alert('Fetch failed');
  }
});
