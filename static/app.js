/* Shade America Portal — app.js */

// ---- Sidebar mobile toggle ----
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('overlay');
const mobileBtn = document.getElementById('mobileMenuBtn');

if (mobileBtn) {
    mobileBtn.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('open');
    });
}
if (overlay) {
    overlay.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.remove('open');
    });
}

// ---- Jobs table search ----
const searchInput = document.getElementById('jobSearch');
if (searchInput) {
    searchInput.addEventListener('input', () => {
        const q = searchInput.value.toLowerCase();
        document.querySelectorAll('.job-row').forEach(row => {
            row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
    });
}

// ---- Upload area toggle ----
function toggleUpload() {
    const area = document.getElementById('uploadArea');
    if (area) area.style.display = area.style.display === 'none' ? 'block' : 'none';
}

// ---- Auto-dismiss flash messages ----
document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
        el.style.transition = 'opacity .5s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
    }, 4000);
});
