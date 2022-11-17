# Logreader
Simple python-script I use to analyze log-files to quickly extract the commonly relevant error-messages. The script prints the results to terminal and by default outputs to file `outfile.txt`.

## Usage
Running the script with `python logreader.py` and selecting the logfile to be analyzed. The following can be adjusted:

`display_separator`:   (True/false) Whether or not to display separators between errors  
`write_to_file`:       (True/false) Writing to a file or just terminal  
`general_limit`:       Overrides the specific limits and sets a general limit of outputted errors  
`context`:             The number of error-messages written above and below the output error-messages  

You can also enter a `custom pattern` which returns case insensitive hits on the pattern.

Inside the code, you can change the following variables to adjust the output:

`limit_output`:        Limits output num of specific errors  