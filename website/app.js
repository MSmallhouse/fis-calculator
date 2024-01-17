const lambdaURL = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";

const url = document.getElementById("urlInput");
const eventSelector = document.getElementById("eventSelector");
const minPenalty = document.getElementById("minPenalty");
const form = document.getElementById("userInfo");
const loader = document.getElementById("loader");
const results = document.getElementById("results");
const submitBtn = document.getElementById("submitBtn");
form.setAttribute("action", lambdaURL);
form.setAttribute("method", "get");

loader.style.display = "none";

submitBtn.addEventListener("click", () => {
    loader.style.display = "block";
})

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
            console.log(data);
            // handle response from Lambda function
            for (let i=0; i<data.length; i++) {
                const header = document.createElement("h4");
                header.textContent = `${data[i]}`;
                results.append(header);
            }
        })
        .catch(error => {
            loader.style.display = "none";
            console.log("Error: ", error);
            const header = document.createElement("h4");
            header.textContent = "Something went wrong...";
            results.append(header);
        });
}