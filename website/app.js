document.addEventListener('DOMContentLoaded', function() {
    formSubmitBehavior();
    applyStyling();
    //toggleHeaderOnScroll();
});

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

function applyStyling() {
    const select = document.querySelectorAll("select");
    const submitBtn = document.getElementById("submitBtn");

    select.forEach(selectElement => {
        selectElement.onchange = function() {
            selectElement.classList.add('option-selected-color');
        }
    });

    submitBtn.addEventListener("click", () => {
        loader.style.display = "block";
    })
}

function toggleHeaderOnScroll() {
  const header = document.querySelector('.contact');
  const threshold = 10; // scroll up was being detected a little too easily on mobile, add this to make sure they're really scrolling up
  let lastScroll = 0;

  window.addEventListener('scroll', function () {
    let scroll = window.scrollY || this.document.documentElement.scrollTop;
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