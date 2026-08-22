document.addEventListener('DOMContentLoaded', function() {
    let currentDate = new Date();
    currentDate = formatDatestring(currentDate);

    formSubmitBehavior();
    getFisAppRaces(currentDate);
    datePickerInit();
    applyStyling();
    //validateForm();
    //toggleHeaderOnScroll();
});

// used by both the scoring form and the FIS race list
const lambdaURL = "https://hsa35mz4zsbu6nqwlb5jvkk4o40jruqd.lambda-url.us-east-2.on.aws/";

function formatDatestring(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0') // months are zero-indexed
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

// sometimes, run times don't come through or come through as 0 seconds - don't use these
function isValidRunTime(time) {
    return time && time != "0.00";
}

function calculatePersonalBestColor(score, points) {
    let multiplier = (points-score) / points
    // max darkness is scoring 25% lower than current points
    // scale this by 0.5 then add 0.5 for resulting range of 0.5 to 1 opacity
    return Math.min( (multiplier/0.25), 1) * 0.5 + 0.5
}

function createTableHead(data) {
    const tableHead = document.createElement("thead");

    const headerRow = document.createElement("tr");
    headerRow.innerHTML = `
        <th>Pl</th>
        <th>Name</th>
        `;
    
    if (data.isStartlist) {
        headerRow.innerHTML += `
        <th>Points</th>
        `
        tableHead.append(headerRow);
        return tableHead;
    }

    // add times for FIS Livetiming
    if (data.hasRunTimes && !data.isStartlist) {
        if (data.event == 'SGpoints' || data.event == 'DHpoints') {
            headerRow.innerHTML += `
            <th>R1</th>
            `;
        } else if (data.areScoresProjections) {
            headerRow.innerHTML += `
            <th>R1</th>
            <th>Projected Total</th>
            `
        } else if (data.hasThirdRun) {
            headerRow.innerHTML += `
            <th>R1</th>
            <th>R2</th>
            <th>R3</th>
            <th>Total</th>
            `;
        } else {
            headerRow.innerHTML += `
            <th>R1</th>
            <th>R2</th>
            <th>Total</th>
            `;
        }
    }

    const scoreString = data.areScoresProjections ? 'Projected Score' : 'Score'
    headerRow.innerHTML += `
        <th>Points</th>
        <th>${scoreString}</th>
        `;

    tableHead.append(headerRow);
    return tableHead;
}

function formSubmitBehavior() {
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

        // Fire Google Analytics event
        gtag('event', 'form_fill', {
            event_category: 'engagement',
            event_label: url.value.trim(),
        })
        console.log('GA key event fired');

        // make sure form is completed
        if (!url.value.trim() || !minPenalty.value || !eventSelector.value) {
            return;
        }

        loader.style.display = "block";
        results.innerHTML = "";
        // attach form responses to url as query string
        const requestURL = `${lambdaURL}?url=${encodeURIComponent(url.value)}
                            &min-penalty=${minPenalty.value}
                            &event=${eventSelector.value}`

        fetch(requestURL)
            .then(async response => {
                if (!response.ok) {
                    let errorMsg = "Something went wrong...";
                    // look for custom error messages, these are thrown in app.js
                    // note that the default error message is for status code 500
                    try {
                        const errJson = await response.json();
                        if (response.status !== 500 && errJson && errJson.error) {
                            errorMsg = errJson.error;
                        }
                    } catch (e) {}
                    throw new Error(errorMsg);
                }
                return response.json();
            })
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
                const tableHead = createTableHead(data);
                table.append(tableHead);

                const tableBody = document.createElement("tbody");

                data.results.forEach(result => {
                    const row = document.createElement("tr");
                    const placeCell = document.createElement("td");
                    const nameCell = document.createElement("td");

                    placeCell.textContent = result.place;
                    nameCell.textContent = result.name;
                    nameCell.classList.add("text-break");
                    row.append(placeCell);
                    row.append(nameCell);
                    if (data.isStartlist) {
                        const pointsCell = document.createElement("td");
                        pointsCell.textContent = result.points.toFixed(2);
                        pointsCell.classList.add("text-center");
                        row.append(pointsCell);
                        tableBody.append(row);
                        return;
                    }

                    if (data.hasRunTimes) {
                        table.classList.add('run-times');
                        table.style.fontSize = '12px';
                        const r1Cell = document.createElement('td');
                        const resultCell = document.createElement('td');

                        if ((data.event == 'SLpoints' || data.event == 'GSpoints') && !data.areScoresProjections && !data.hasThirdRun) {
                            if (isValidRunTime(result.r1_time)) {
                                r1Cell.textContent = `${result.r1_time || ''} (${result.r1_rank || ''})`
                            }
                            row.append(r1Cell);

                            const r2Cell = document.createElement('td');
                            if (isValidRunTime(result.r2_time)) {
                                r2Cell.textContent = `${result.r2_time || ''} (${result.r2_rank || ''})`
                            }
                            row.append(r2Cell);
                        }

                        // shitty repeated code but just put this to get 3 run slalom feature out
                        if (data.hasThirdRun) {
                            if (isValidRunTime(result.r1_time)) {
                                r1Cell.textContent = `${result.r1_time || ''} (${result.r1_rank || ''})`
                            }
                            row.append(r1Cell);

                            const r2Cell = document.createElement('td');
                            if (isValidRunTime(result.r2_time)) {
                                r2Cell.textContent = `${result.r2_time || ''} (${result.r2_rank || ''})`
                            }
                            row.append(r2Cell);

                            const r3Cell = document.createElement('td');
                            if (isValidRunTime(result.r3_time)) {
                                r3Cell.textContent = `${result.r3_time || ''} (${result.r3_rank || ''})`
                            }
                            row.append(r3Cell);
                        }

                        if (data.areScoresProjections) {
                            if (isValidRunTime(result.r1_time)) {
                                r1Cell.textContent = `${result.r1_time || ''} (${result.r1_rank || ''})`
                            }
                            row.append(r1Cell);
                        }

                        resultCell.textContent = `${result.time || ''}`
                        row.append(resultCell);
                    }

                    const pointsCell = document.createElement("td");
                    const scoreCell = document.createElement("td");

                    pointsCell.textContent = result.points.toFixed(2);
                    pointsCell.classList.add("text-center");

                    scoreCell.textContent = result.score.toFixed(2);
                    scoreCell.classList.add("text-center");
                    if (result.score < result.points) {
                        scoreCell.classList.add("personal-best");
                        scoreCell.style.opacity = calculatePersonalBestColor(result.score, result.points);
                    }

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
                results.innerHTML = "";
                console.log("Error: ", error);
                const header = document.createElement("h4");
                header.textContent = error.message || "Something went wrong...";
                results.append(header);
            });
    }

}

function getFisAppRaces(dateString) {
    const fisAppTableBody = document.querySelector('.fis-app-table-body');
    const tableLoader = document.getElementById('table-loader');

    fisAppTableBody.innerHTML = "";

    // This used to fetch https://www.fis-ski.com/DB/alpine-skiing/live.html and
    // scrape it here. FIS's new backend answers every request with
    // `access-control-allow-origin: https://www.fis-ski.com` no matter who asks,
    // so the browser fetches the page and then refuses to hand it over - a 200
    // that reads as a failure. The lambda fetches and parses it instead, and
    // returns the race already matched to a codex, event and penalty.
    fetch(`${lambdaURL}?action=races`)
        .then(response => {
            if (!response.ok) throw new Error(`race list unavailable (${response.status})`);
            return response.json();
        })
        .then(data => {
            tableLoader.style.display = 'none';

            const races = (data.races || []).filter(race => race.date === dateString);
            if (races.length === 0) {
                fisAppTableBody.innerHTML =
                    `<tr><td colspan="3">No FIS races listed for this date.</td></tr>`;
                return;
            }

            races.forEach(race => {
                const tableRow = document.createElement('tr');
                tableRow.className = 'fis-table-row';
                tableRow.setAttribute('codex', race.codex);
                tableRow.setAttribute('category', race.minPenalty);
                tableRow.setAttribute('event', race.eventCode);
                tableRow.innerHTML = `
                    <td>${race.country}<br>${race.location}</td>
                    <td>${race.event}</td>
                    <td>${race.gender}</td>
                `;
                fisAppTableBody.appendChild(tableRow);
            });

            const url = document.getElementById("urlInput");
            const eventSelector = document.getElementById("eventSelector");
            const minPenalty = document.getElementById("minPenalty");
            const submitBtn = document.getElementById("submitBtn");
            const form = document.getElementById("userInfo");

            document.querySelectorAll('.fis-table-row').forEach(row => {
                row.addEventListener("click", () => {
                    url.value = row.getAttribute('codex');
                    eventSelector.value = row.getAttribute('event');
                    minPenalty.value = row.getAttribute('category');
                    submitBtn.click();
                    form.scrollIntoView({behavior: 'smooth'});
                });
            });
        })
        .catch(error => {
            // without this the loader spins forever and the failure is invisible
            tableLoader.style.display = 'none';
            fisAppTableBody.innerHTML =
                `<tr><td colspan="3">Could not load the FIS race list right now.</td></tr>`;
            console.error('getFisAppRaces:', error);
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
    const collapsibleRaces = document.querySelector('.collapsible-races');
    const collapsibleArrow = document.getElementById('collapsible-arrow');
    const fisAppTable = document.querySelector('.fis-app-table');
    const datePicker = document.getElementById('date-picker-container');

    select.forEach(selectElement => {
        selectElement.onchange = function() {
            selectElement.classList.add('option-selected-color');
        }
    });

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
    if (Math.abs(scroll-lastScroll) < threshold) {
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

//function validateForm() {
//    const form = document.getElementById("userInfo");
//    const inputs = form.querySelectorAll("input, select");
//    const submitBtn = document.getElementById("submitBtn");
//
//    function checkFormValidity() {
//        let isValid = true;
//        inputs.forEach(input => {
//            console.log(input.value.trim())
//            if (!input.value.trim() || input.value === "null") {
//                isValid = false;
//            }
//        });
//        if (isValid) {
//            console.log('invalid');
//            submitBtn.setAttribute('disabled', 'true');
//        } else {
//            console.log('valid');
//            submitBtn.removeAttribute('disabled');
//        }
//    }
//
//    inputs.forEach(input => {
//        input.addEventListener('input', checkFormValidity);
//        input.addEventListener('change', checkFormValidity);
//    });
//}