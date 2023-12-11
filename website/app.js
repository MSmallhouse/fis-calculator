const lambdaEndpoint = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";

const url = document.getElementById("urlInput");
const submitResponse = document.getElementById("response");
const form = document.getElementById("userInfo");
form.setAttribute("action", lambdaEndpoint);
form.setAttribute("method", "get");

form.onsubmit = e => {
    e.preventDefault();


    fetch(`${lambdaEndpoint}?url=${encodeURIComponent(url)}`)
        .then(response => response.json())
        .then(data => {
            // handle response from Lambda function
            console.log(data);
        })
        .catch(error => {
            console.log("Error: ", error);
        });
}

    /*let data = {};
    Array.from(form).map(input => (data[input.id] = input.value));
    console.log("Sending: ", JSON.stringify(data));
    submitResponse.innerHTML = "Sending...";*/

    // Create the AJAX request
    /*let xhr = new XMLHttpRequest();
    xhr.open(form.method, lambdaEndpoint, true);
    xhr.setRequestHeader("Accept", "application/json; charset=utf-8");
    xhr.setRequestHeader("Content-Type", "application/json; charset-utf-8");

    // send the collected data as JSON
    xhr.send(JSON.stringify(data));

    xhr.onloadend = response => {
        if (response.target.status === 200) {
            form.reset();
            submitResponse.innerHTML = "Form Submitted";
        } else {
            submitResponse.innerHTML = "Submission Error!";
            console.error(JSON.parse(response));
        }
    }
    
}*/


/*const urlForm = document.getElementById("urlInput");

urlForm.addEventListener("submit", function(event) {
    // prevent default form submission
    event.preventDefault();

    const url = document.getElementById("urlInput");
    console.log("pressed");

    // send GET request
    fetch(`${lambdaEndpoint}?url=${encodeURIComponent(url)}`)
        .then(response => response.json())
        .then(data => {
            // handle response from Lambda function
            console.log(data);
        })
        .catch(error => {
            console.log("Error: ", error);
        });
});*/