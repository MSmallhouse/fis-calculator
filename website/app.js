const lambdaURL = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";

const url = document.getElementById("urlInput");
const eventSelector = document.getElementById("eventSelector");
const minPenalty = document.getElementById("minPenalty");
const submitResponse = document.getElementById("response");
const form = document.getElementById("userInfo");
form.setAttribute("action", lambdaURL);
form.setAttribute("method", "get");

form.onsubmit = e => {
    e.preventDefault();
    // attach form responses to url as query string
    const requestURL = `${lambdaURL}?url=${encodeURIComponent(url.value)}
                        &min-penalty=${minPenalty.value}
                        &event=${eventSelector.value}`

    fetch(requestURL).then(response => response.json())
        .then(data => {
            console.log(data);
            // handle response from Lambda function
            data.forEach(element => {
                const header = document.createElement("h4");
                header.textContent = element;
                document.body.append(header);
            });
        })
        .catch(error => {
            console.log("Error: ", error);
        });
}