# Logreader
Simple python-script I use to analyze log-files to quickly extract the commonly relevant error-messages. The script prints the results to terminal and by default outputs to file `outfile.txt`.

## Usage
Renaming the file to be analyzed to `infile.txt` and running the script with `python logreader.py`

Inside the code, you can change the following variables to adjust the output:

`context`:             The number of error-messages written above and below the output error-messages  
`display_separator`:   (True/false) Whether or not to display separators between errors  
`write_to_file`:       (True/false) Writing to a file or just terminal  
`limit_output`:        Limits output num of specific errors  
`general_limit`:       Overrides the specific limits and sets a general limit