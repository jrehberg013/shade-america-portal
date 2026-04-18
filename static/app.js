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

// ---- Estimator dynamic rows ----
const rowCounters = { sail: 1, hip: 1, cpost: 1, cbeam: 1 };

const sailOptions = `
    <option value="">-- Size --</option>
    <option value='5" SCH40'>5" SCH40</option>
    <option value='6" SCH40'>6" SCH40</option>
    <option value='8" SCH40'>8" SCH40</option>`;

const hipOptions = `
    <option value="">-- Size --</option>
    <option value='5" SCH40'>5" SCH40</option>
    <option value='6" SCH40'>6" SCH40</option>
    <option value='8" SCH40'>8" SCH40</option>
    <option value='3" OD Galv Tubing'>3" OD Galv</option>
    <option value='4" OD Galv Tubing'>4" OD Galv</option>
    <option value='5" OD Galv Tubing'>5" OD Galv</option>`;

const hssOptions = `
    <option value="">-- Size --</option>
    <option value="4x4">4x4 HSS</option>
    <option value="4x6">4x6 HSS</option>
    <option value="4x8">4x8 HSS</option>`;

const attachOptions = `
    <option value="All Thread">All Thread</option>
    <option value="Weld Lug">Weld Lug</option>
    <option value="Wall Mount">Wall Mount</option>
    <option value="Drive Post">Drive Post</option>
    <option value="Surface Mount">Surface Mount</option>`;

function addRow(prefix, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const idx = rowCounters[prefix]++;
    const id = prefix + '_' + idx;

    const div = document.createElement('div');
    div.className = 'pole-row';
    div.id = id;

    let sizeOpts, attachCol = '';
    if (prefix === 'sail') {
        sizeOpts = sailOptions;
        attachCol = `<select name="${prefix}_attach_${idx}">${attachOptions}</select>`;
    } else if (prefix === 'hip') {
        sizeOpts = hipOptions;
        attachCol = `<span></span>`;
    } else {
        sizeOpts = hssOptions;
        attachCol = `<span></span>`;
    }

    div.innerHTML = `
        <select name="${prefix}_size_${idx}" class="pipe-select">${sizeOpts}</select>
        <input type="number" name="${prefix}_len_${idx}" placeholder="ft" min="1" max="40" step="0.5">
        <input type="number" name="${prefix}_qty_${idx}" placeholder="qty" min="1" max="50">
        ${attachCol}
        <button type="button" class="btn btn-sm btn-danger" onclick="removeRow('${id}')">✕</button>`;

    container.appendChild(div);
    updateCount(prefix);
}

function removeRow(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
    // recalc count for the prefix
    const prefix = id.split('_')[0];
    updateCount(prefix);
}

function updateCount(prefix) {
    const containerId = prefix + 'Rows';
    const container = document.getElementById(containerId);
    if (!container) return;
    const count = container.querySelectorAll('.pole-row').length;
    const inp = document.getElementById(prefix + '_count');
    if (inp) inp.value = count;
}

// ---- Auto-dismiss flash messages ----
document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => {
        el.style.transition = 'opacity .5s';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 500);
    }, 4000);
});
