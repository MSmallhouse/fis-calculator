document.addEventListener('DOMContentLoaded', function() {
    let currentDate = new Date();
    currentDate = formatDatestring(currentDate);

    formSubmitBehavior();
    getFisAppRaces(currentDate);
    datePickerInit();
    applyStyling();
    //toggleHeaderOnScroll();
});

function formatDatestring(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0') // months are zero-indexed
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

function formSubmitBehavior() {
    const lambdaURL = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";
    const url = document.getElementById("urlInput");
    const eventSelector = document.getElementById("eventSelector");
    const minPenalty = document.getElementById("minPenalty");
    const form = document.getElementById("userInfo");
    const loader = document.getElementById("loader");
    const results = document.getElementById("results");

    form.setAttribute("action", lambdaURL);
    form.setAttribute("method", "get");

    form.onsubmit = e => {
        e.preventDefault();
        results.innerHTML = "";
        // attach form responses to url as query string
        const requestURL = `${lambdaURL}?url=${encodeURIComponent(url.value)}
                            &min-penalty=${minPenalty.value}
                            &event=${eventSelector.value}`

        fetch(requestURL).then(response => response.json())
            .then(data => {
                loader.style.display = "none";
                // handle response from Lambda function
                if (data.notFound) {
                    const warning = document.createElement("p");
                    warning.textContent = "results might be off, points not found for:";
                    const notFound = document.createElement("p");
                    notFound.textContent = `${data.notFound}`
                    results.append(warning);
                    results.append(notFound);
                }

                const table = document.createElement("table");
                const tableHead = document.createElement("thead");
                const tableBody = document.createElement("tbody");
                const headerRow = document.createElement("tr");
                headerRow.innerHTML = `
                    <th>Pl</th>
                    <th>Name</th>
                    <th>Points</th>
                    <th>Score</th>`;
                tableHead.append(headerRow);
                table.append(tableHead);

                data.results.forEach(result => {
                    const row = document.createElement("tr");
                    const placeCell = document.createElement("td");
                    const nameCell = document.createElement("td");
                    const pointsCell = document.createElement("td");
                    const scoreCell = document.createElement("td");

                    placeCell.textContent = result.place;
                    nameCell.textContent = result.name;
                    nameCell.classList.add("text-break");
                    pointsCell.textContent = result.points.toFixed(2);
                    pointsCell.classList.add("text-center");
                    scoreCell.textContent = result.score.toFixed(2);
                    scoreCell.classList.add("text-center");
                    if (result.score < result.points) {
                        scoreCell.classList.add("personal-best");
                    }
                    row.append(placeCell);
                    row.append(nameCell);
                    row.append(pointsCell);
                    row.append(scoreCell);
                    tableBody.append(row);
                });

                table.append(tableBody);
                results.append(table)
                results.scrollIntoView({behavior: 'smooth'});
            })
            .catch(error => {
                loader.style.display = "none";
                console.log("Error: ", error);
                const header = document.createElement("h4");
                header.textContent = "Something went wrong...";
                results.append(header);
            });
    }

}

function getFisAppRaces(dateString) {
    const raceCategoryToPenalty = {
        'OWG': '0',
        'WC': '0',
        'WSC': '0',
        'COM': '0',
        'WQUA': '0',
        'ANC': '15',
        'EC': '15',
        'ECOM': '15',
        'FEC': '15',
        'NAC': '15',
        'SAC': '15',
        'UVS': '15',
        'WJC': '15',
        'EQUA': '23',
        'NC': '20',
        'AWG': '23',
        'CISM': '23',
        'CIT': '40',
        'CITWC': '40',
        'CORP': '23',
        'EYOF': '23',
        'FIS': '23',
        'FQUA': '23',
        'JUN': '23',
        'NJC': '23',
        'NJR': '23',
        'UNI': '23',
        'YOG': '23',
        'ENL': '60',
        'TRA': '0',
    };
    const eventNameToCategory = {
        'Slalom': 'SLpoints',
        'Giant Slalom': 'GSpoints',
        'Super G': 'SGpoints',
        'Downhill': 'DHpoints',
        'Downhill Training': 'DHpoints',
    }
    const fisAppTableBody = document.querySelector('.fis-app-table-body');
    const tableLoader = document.getElementById('table-loader');

    fisAppTableBody.innerHTML = "";
    fetch('https://www.fis-ski.com/DB/alpine-skiing/live.html')
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const raceRows = doc.querySelectorAll('.g-row');

            tableLoader.style.display = 'none';
            raceRows.forEach(row => {
                const splitRowItems = row.querySelectorAll('.split-row__item');
                const codex = splitRowItems[1].textContent.trim();
                const location = splitRowItems[2].textContent.trim();
                const displayDate = row.querySelector('.timezone-date').textContent.trim();
                const raceDate = row.querySelector('.timezone-date').getAttribute('data-date');
                const countryCode = row.querySelector('.country__name-short').textContent;
                const raceCategory = splitRowItems[4].textContent.trim();
                const event = splitRowItems[5].textContent.trim();
                const gender = row.querySelector('.gender__item').textContent;

                const live = row.querySelector('.live__content');
                let isLive = ''
                if(live) {
                    isLive = live.textContent === 'live' ? 'Y' : 'N';
                }

                if(raceDate === dateString) {
                    const tableRow = document.createElement('tr');
                    tableRow.className = 'fis-table-row'
                    tableRow.setAttribute('codex', codex);
                    tableRow.setAttribute('category', raceCategoryToPenalty[raceCategory]);
                    tableRow.setAttribute('event', eventNameToCategory[event]);
                    tableRow.innerHTML = `
                        <td>${countryCode}<br>${location}</td>
                        <td>${event}</td>
                        <td>${gender}</td>
                    `;
                    fisAppTableBody.appendChild(tableRow);
                }
            });
            const tableRows = document.querySelectorAll('.fis-table-row');
            const url = document.getElementById("urlInput");
            const eventSelector = document.getElementById("eventSelector");
            const minPenalty = document.getElementById("minPenalty");
            const submitBtn = document.getElementById("submitBtn");
            const form = document.getElementById("userInfo");

            tableRows.forEach(row => {
                row.addEventListener("click", () => {
                    url.value = row.getAttribute('codex');
                    eventSelector.value = row.getAttribute('event');
                    minPenalty.value = row.getAttribute('category');
                    submitBtn.click();
                    form.scrollIntoView({behavior: 'smooth'});
                });
            });
        });
}

function datePickerInit() {
    const currentDateSpan = document.getElementById('current-date');
    const prevDayButton = document.getElementById('prev-day');
    const nextDayButton = document.getElementById('next-day');

    let currentDate = new Date();

    function updateDateDisplay() {
        //currentDateSpan.textContent = currentDate.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});
        currentDateSpan.textContent = currentDate.toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'});
    }

    function changeDate(days) {
        const tableLoader = document.getElementById('table-loader');
        tableLoader.style.display = 'block';

        currentDate.setDate(currentDate.getDate() + days);
        updateDateDisplay();
        getFisAppRaces( formatDatestring(currentDate) );
    }

    prevDayButton.addEventListener('click', () => {
      changeDate(-1);
    });

    nextDayButton.addEventListener('click', () => {
      changeDate(1);
    });

    updateDateDisplay();
}

function applyStyling() {
    const select = document.querySelectorAll("select");
    const submitBtn = document.getElementById("submitBtn");
    const collapsibleRaces = document.querySelector('.collapsible-races');
    const collapsibleArrow = document.getElementById('collapsible-arrow');
    const fisAppTable = document.querySelector('.fis-app-table');
    const datePicker = document.getElementById('date-picker-container');

    select.forEach(selectElement => {
        selectElement.onchange = function() {
            selectElement.classList.add('option-selected-color');
        }
    });

    submitBtn.addEventListener("click", () => {
        loader.style.display = "block";
    })

    collapsibleArrow.style.transition = 'transform 0.2s';
    collapsibleRaces.addEventListener("click", () => {
        const isHidden = fisAppTable.style.display === 'none';

        collapsibleArrow.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
        fisAppTable.style.display = isHidden ? 'block' : 'none';
        datePicker.style.display = isHidden ? 'flex' : 'none';
    });
}

function toggleHeaderOnScroll() {
  const header = document.querySelector('.contact');
  const threshold = 10; // scroll up was being detected a little too easily on mobile, add this to make sure they're really scrolling up
  let lastScroll = 0;

  window.addEventListener('scroll', function () { let scroll = window.scrollY || this.document.documentElement.scrollTop;
    if(Math.abs(scroll-lastScroll) < threshold) {
      return;
    }
    
    if(scroll > lastScroll) { // hide header on scroll down
      header.style.top = '-120px';
    } else { // show header on scroll up
      header.style.top = '-1px';
    }
    lastScroll = scroll;
  });
}