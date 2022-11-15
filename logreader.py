import re
import os
from termcolor import colored
import PySimpleGUI as sg

#TODO: Add custom pattern-match (Future: Add several patterns in list)
#TODO: Split printing into functions
#TODO: Fix small bug with limiter cutting off end of context
#TODO: Add context for general errors as well
#TODO: Single color of word on "Error:"-messages (And maybe color for ---> arrow)
#TODO: Expand PySimpleGui integration 

#Log analysis project

def name(name):
    dots = NAME_SIZE-len(name)-2
    return sg.Text(name + ' ' + '•'*dots, size=(NAME_SIZE,1), justification='r',pad=(0,0), font='Courier 10')

def main():
    
    context = 3
    printcolor_gen = "blue"
    
    display_separator = True
    write_to_file = True
    
    limit_output = 0
    limit_output_gen = 0
    limit_output_wargen = 0
    limit_output_failed = 0
    limit_output_fatal = 0
    
    general_limit = 0
    
    version = "Logreader v0.12"
    
    #PySimpleGUI file-select
    layout = [[sg.T("")], 
        [sg.Text("Choose a logfile: "), 
            sg.Input(key="-IN2-" ,
            change_submits=True), 
            sg.FileBrowse(key="-IN-")],
        [sg.Button("Submit")]]
    
    window = sg.Window(version, layout, size=(535,115))    
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event=="Exit":
            break
        elif event == "Submit":
            filename = values["-IN-"]
            break
    
    
    #PySimpleGUI value-select  
    def_toggle_size = (19,1)
    def_box_size = (19,1)
    
    layout = [
        [sg.Text('')],
        [sg.Text('Choose values:')],
        [sg.Text(('Display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='SEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Write to file'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FILEWRITE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Output error limit:'), size = def_box_size), sg.Input('0', enable_events=True,  key='ERRIN', s=3)],
        [sg.Text(('Context around errors:'), size = def_box_size), sg.Input('3', enable_events=True,  key='CONTIN', s=3)],
        [sg.Text('')],
        [sg.Button("Submit")]
    ]
    
    window = sg.Window(version, layout, size=(350,300))

    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        elif event == 'SEPARATOR':
            window['SEPARATOR'].metadata = not window['SEPARATOR'].metadata
            window['SEPARATOR'].update(image_data=toggle_btn_on if window['SEPARATOR'].metadata else toggle_btn_off)
            display_separator = window['SEPARATOR'].metadata
        elif event == 'FILEWRITE':
            window['FILEWRITE'].metadata = not window['FILEWRITE'].metadata
            window['FILEWRITE'].update(image_data=toggle_btn_on if window['FILEWRITE'].metadata else toggle_btn_off)
            write_to_file = window['FILEWRITE'].metadata
        elif event == "Submit":
            display_separator = window['SEPARATOR'].metadata
            write_to_file = window['FILEWRITE'].metadata
            general_limit = int(values['ERRIN'])
            context = int(values['CONTIN'])
            break
        elif event == 'ERRIN' and len(values['ERRIN']) and values['ERRIN'][-1] not in ('0123456789'):
            window['ERRIN'].update(values['ERRIN'][:-1])
        elif event == 'CONTIN' and len(values['CONTIN']) and values['CONTIN'][-1] not in ('0123456789'):
            window['CONTIN'].update(values['CONTIN'][:-1])
    window.close()
    
    if(general_limit != 0):
        limit_output = general_limit
        limit_output_gen = general_limit
        limit_output_wargen = general_limit
        limit_output_failed = general_limit
        limit_output_fatal = general_limit
    
    has_limit = (limit_output != 0)
    has_limit_gen = (limit_output_gen != 0)        
    has_limit_wargen = (limit_output_wargen != 0)
    has_limit_failed = (limit_output_failed != 0)
    has_limit_fatal = (limit_output_fatal != 0)

    #Reading first, then formatting
    f = open(filename, "r")
    if write_to_file:
        w = open("outfile.txt", "w")
        
    logoutput = f.read().splitlines()

    for x in range(len(logoutput)):

        space_string = ""
        num_len = len(str(x + 1))
        
        if x >= 0:
            for z in range(7-(num_len)):
                space_string += " "
        
        logoutput[x] = str(x + 1) + space_string + "-> " + logoutput[x]

    #Types of strings we are looking for (errors, warnings, failed, fatal)
    err_msg1 = "error:"
    err_msg_arr = []

    err_gen = "error"
    errgen_msg_arr = []

    fail_gen = "failed"
    failgen_msg_arr = []

    fatal_gen = "fatal"
    fatalgen_msg_arr = []

    war_msg1 = "warning:"
    war_msg_arr = []


    #Appending the error-strings to the appropriate array, and adding context
    err_num = 0
    for x in range(len(logoutput)):

        if (err_msg1 in logoutput[x].lower()):        
            
            #Add context before the error-message
            cont_num = context
            for z in range(context):
                if (cont_num > 0):
                    if(x - cont_num) > 0:
                        if(logoutput[x - cont_num] not in err_msg_arr):
                            err_msg_arr.append(logoutput[x - cont_num])
                    cont_num += -1

            #Add the error-message
            err_msg_arr.append(logoutput[x])
            err_num +=1
            
            #Add context after the error-message
            for c in range(context):
                if((x + (c + 1)) > (len(logoutput) - 1)) or ("error:" in logoutput[x + (c + 1)].lower()):
                    break
                err_msg_arr.append(logoutput[x + (c + 1)])
            
            if display_separator:
                err_msg_arr.append(" ")
        
        #Add the generic messages
        if (war_msg1 in logoutput[x].lower()):
            war_msg_arr.append(logoutput[x])
        if (err_gen in logoutput[x].lower()) and ("error:" not in logoutput[x].lower()):
            errgen_msg_arr.append(logoutput[x])
        if (fail_gen in logoutput[x].lower()):
            failgen_msg_arr.append(logoutput[x])
        if (fatal_gen in logoutput[x].lower()):
            fatalgen_msg_arr.append(logoutput[x])

    #Checking for spaces that we dont need (places where separating errors do not make sense)        
    if display_separator:

        for x in range(len(err_msg_arr)):
            
            res = err_msg_arr[x].split()
            if not res:
                if(((x - 1) >= 0) and ((x + 1) < len(err_msg_arr))):
                    
                    #Regex to find first number in string from first element in comp.
                    #This part of the code might be unnecessarily complicated and a simple
                    #row-comparison might suffice, but it works.
                    comp1 = err_msg_arr[x - 1].split()
                    comp1_res = re.search('[0-9]+', comp1[0]).group()
                    
                    comp2 = err_msg_arr[x + 1].split()
                    comp2_res = re.search('[0-9]+', comp2[0]).group()
                    
                    if(int(comp1_res) == (int(comp2_res) - 1)):
                        err_msg_arr[x] = "remove"

        v = len(err_msg_arr) - 1
        for x in range(len(err_msg_arr)):
            
            if(err_msg_arr[v] == "remove"):
                err_msg_arr.pop(v)
            v += -1
            
        for x in range(len(err_msg_arr)):
            if(err_msg_arr[x] == " "):
                err_msg_arr[x] = "-------->"
    
    #Print results
    print("\n" + version + "\n")
    print("Number of errors in this file:           " + str(err_num))
    print("Number of generic errors in this file:   " + str(len(errgen_msg_arr)))
    print("Number of warnings in this file:         " + str(len(war_msg_arr)))
    print("Number of generic failures in this file: " + str(len(failgen_msg_arr)))
    print("Number of generic fatals in this file:   " + str(len(fatalgen_msg_arr)))
    print()
    print("Printed with context of:                 " + str(context))
    print("Lines in file:                           " + str(len(logoutput)))
    print()
    
    #Write to file
    if write_to_file:
        w.write("\n" + version + "\n\n")
        w.write("Number of errors in this file:           " + str(err_num) + "\n")
        w.write("Number of generic errors in this file:   " + str(len(errgen_msg_arr)) + "\n")
        w.write("Number of warnings in this file:         " + str(len(war_msg_arr)) + "\n")
        w.write("Number of generic failures in this file: " + str(len(failgen_msg_arr)) + "\n")
        w.write("Number of generic fatals in this file:   " + str(len(fatalgen_msg_arr)) + "\n")
        w.write("\n")
        w.write("Printed with context of:                 " + str(context) + "\n")
        w.write("Lines in file:                           " + str(len(logoutput)) + "\n")
        w.write("\n")

    os.system('color')

    print("------------------------------------------------")
    print("Errors contained:                              |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for i, x in enumerate(err_msg_arr):
        if "error:" in err_msg_arr[i].lower():
            print(colored(x, 'red', attrs=["bold"]))
            err_count += 1
        else:
            print(x)
        if has_limit and (err_count == limit_output):
            print("\nLimited, showing " + str(limit_output) + " out of " + str(err_num) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(err_num) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("------------------------------------------------\n")
        w.write("Errors contained:                              |\n")
        w.write("------------------------------------------------\n")
        for i, x in enumerate(err_msg_arr):
            if "error:" in err_msg_arr[i].lower():
                w.write(x + "\n")
                err_count += 1
            else:
                w.write(x + "\n")
            if has_limit and (err_count == limit_output):
                w.write("\nLimited, showing " + str(limit_output) + " out of " + str(err_num) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(err_num) + " elements.\n")
    print()
    print("------------------------------------------------")
    print("Generic errors contained:                      |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in errgen_msg_arr:
        
        pattern = re.compile(err_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_gen and (err_count == limit_output_gen):
            print("\nLimited, showing " + str(limit_output_gen) + " out of " + str(len(errgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(errgen_msg_arr)) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic errors contained:                      |\n")
        w.write("------------------------------------------------\n")
        for x in errgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_gen and (err_count == limit_output_gen):
                w.write("\nLimited, showing " + str(limit_output_gen) + " out of " + str(len(errgen_msg_arr)) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(errgen_msg_arr)) + " elements.\n")
            
    print()
    print("------------------------------------------------")
    print("Warnings contained:                            |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in war_msg_arr:
        
        #Using regex to split the string apart then color the appropriate error-word
        pattern = re.compile(war_msg1, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_wargen and (err_count == limit_output_wargen):
            print("\nLimited, showing " + str(limit_output_wargen) + " out of " + str(len(war_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(war_msg_arr)) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Warnings contained:                            |\n")
        w.write("------------------------------------------------\n")
        for x in war_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_wargen and (err_count == limit_output_wargen):
                w.write("\nLimited, showing " + str(limit_output_wargen) + " out of " + str(len(war_msg_arr)) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(war_msg_arr)) + " elements.\n")

    print()
    print("------------------------------------------------")
    print("Generic failures contained:                    |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in failgen_msg_arr:
    
        pattern = re.compile(fail_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_failed and (err_count == limit_output_failed):
            print("\nLimited, showing " + str(limit_output_failed) + " out of " + str(len(failgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(failgen_msg_arr)) + " elements.")

    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic failures contained:                    |\n")
        w.write("------------------------------------------------\n")
        for x in failgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_failed and (err_count == limit_output_failed):
                w.write("\nLimited, showing " + str(limit_output_failed) + " out of " + str(len(failgen_msg_arr)) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(failgen_msg_arr)) + " elements.\n")

    print()
    print("------------------------------------------------")
    print("Generic fatals contained:                      |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in fatalgen_msg_arr:
        
        pattern = re.compile(fatal_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_fatal and (err_count == limit_output_fatal):
            print("\nLimited, showing " + str(limit_output_fatal) + " out of " + str(len(fatalgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(fatalgen_msg_arr)) + " elements.")

    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic fatals contained:                      |\n")
        w.write("------------------------------------------------\n")
        for x in fatalgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_fatal and (err_count == limit_output_fatal):
                w.write("\nLimited, showing " + str(limit_output_fatal) + " out of " + str(len(fatalgen_msg_arr)) + " elements.")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(fatalgen_msg_arr)) + " elements.")


    f.close()
    if write_to_file:
        w.close()
    

if __name__ == "__main__":

    NAME_SIZE = 23

    toggle_btn_off = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAED0lEQVRYCe1WTWwbRRR+M/vnv9hO7BjHpElMKSlpqBp6gRNHxAFVcKM3qgohQSqoqhQ45YAILUUVDRxAor2VAweohMSBG5ciodJUSVqa/iikaePEP4nj2Ovdnd1l3qqJksZGXscVPaylt7Oe/d6bb9/svO8BeD8vA14GvAx4GXiiM0DqsXv3xBcJU5IO+RXpLQvs5yzTijBmhurh3cyLorBGBVokQG9qVe0HgwiXLowdy9aKsY3g8PA5xYiQEUrsk93JTtjd1x3siIZBkSWQudUK4nZO1w3QuOWXV+HuP/fL85klAJuMCUX7zPj4MW1zvC0Ej4yMp/w++K2rM9b70sHBYCjo34x9bPelsgp/XJksZ7KFuwZjr3732YcL64ttEDw6cq5bVuCvgy/sje7rT0sI8PtkSHSEIRIKgCQKOAUGM6G4VoGlwiqoVd2Za9Vl8u87bGJqpqBqZOj86eEHGNch+M7otwHJNq4NDexJD+59RiCEQG8qzslFgN8ibpvZNsBifgXmFvJg459tiOYmOElzYvr2bbmkD509e1ylGEZk1Y+Ssfan18n1p7vgqVh9cuiDxJPxKPT3dfGXcN4Tp3dsg/27hUQs0qMGpRMYjLz38dcxS7Dm3nztlUAb38p0d4JnLozPGrbFfBFm79c8hA3H2AxcXSvDz7/+XtZE1kMN23hjV7LTRnKBh9/cZnAj94mOCOD32gi2EUw4FIRUMm6LGhyiik86nO5NBdGRpxYH14bbjYfJteN/OKR7UiFZVg5T27QHYu0RBxoONV9W8KQ7QVp0iXdE8fANUGZa0QAvfhhXlkQcmjJZbt631oIBnwKmacYoEJvwiuFgWncWnXAtuVBBEAoVVXWCaQZzxmYuut68b631KmoVBEHMUUrJjQLXRAQVSxUcmrKVHfjWWjC3XOT1FW5QrWpc5IJdQhDKVzOigEqS5dKHMVplnNOqrmsXqUSkn+YzWaHE9RW1FeXL7SKZXBFUrXW6jIV6YTEvMAUu0W/G3kcxPXP5ylQZs4fa6marcWvvZfJu36kuHjlc/nMSuXz+/ejxgqPFpuQ/xVude9eu39Jxu27OLvBGoMjrUN04zrNMbgVmOBZ96iPdPZmYntH5Ls76KuxL9NyoLA/brav7n382emDfHqeooXyhQmARVhSnAwNNMx5bu3V1+habun5nWdXhwJZ2C5mirTesyUR738sv7g88UQ0rEkTDlp+1wwe8Pf0klegUenYlgyg7bby75jUTITs2rhCAXXQ2vwxz84vlB0tZ0wL4NEcLX/04OrrltG1s8aOrHhk51SaK0us+n/K2xexBxljcsm1n6x/Fuv1PCWGiKOaoQCY1Vb9gWPov50+fdEqd21ge3suAlwEvA14G/ucM/AuppqNllLGPKwAAAABJRU5ErkJggg=='
    toggle_btn_on = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAD+UlEQVRYCe1XzW8bVRCffbvrtbP+2NhOD7GzLm1VoZaPhvwDnKBUKlVyqAQ3/gAkDlWgPeVQEUCtEOIP4AaHSI0CqBWCQyXOdQuRaEFOk3g3IMWO46+tvZ+PeZs6apq4ipON1MNafrvreTPzfvub92bGAOEnZCBkIGQgZOClZoDrh25y5pdjruleEiX+A+rCaQo05bpuvJ/+IHJCSJtwpAHA/e269g8W5RbuzF6o7OVjF8D3Pr4tSSkyjcqfptPDMDKSleW4DKIggIAD5Yf+Oo4DNg6jbUBlvWLUNutAwZu1GnDjzrcXzGcX2AHw/emFUV6Sfk0pqcKpEydkKSo9q3tkz91uF5aWlo1Gs/mYc+i7tz4//19vsW2AU9O381TiioVCQcnlRsWeQhD3bJyH1/MiFLICyBHiuzQsD1arDvypW7DR9nzZmq47q2W95prm+I9fXfqXCX2AF2d+GhI98Y8xVX0lnxvl2UQQg0csb78ag3NjEeD8lXZ7pRTgftmCu4864OGzrq+5ZU0rCa3m+NzXlzvoAoB3+M+SyWQuaHBTEzKMq/3BMbgM+FuFCDBd9kK5XI5PJBKqLSev+POTV29lKB8rT0yMD0WjUSYLZLxzNgZvIHODOHuATP72Vwc6nQ4Uiw8MUeBU4nHS5HA6TYMEl02wPRcZBJuv+ya+UCZOIBaLwfCwQi1Mc4QXhA+PjWRkXyOgC1uIhW5Qd8yG2TK7kSweLcRGKKVnMNExWWBDTQsH9qVmtmzjiThQDs4Qz/OUSGTwcLwIQTLW58i+yOjpXDLqn1tgmDzXzRCk9eDenjo9yhvBmlizrB3V5dDrNTuY0A7opdndStqmaQLPC1WCGfShYRgHdLe32UrV3ntiH9LliuNrsToNlD4kruN8v75eafnSgC6Luo2+B3fGKskilj5muV6pNhk2Qqg5v7lZ51nBZhNBjGrbxfI1+La5t2JCzfD8RF1HTBGJXyDzs1MblONulEqPDVYXgwDIfNx91IUVbAbY837GMur+/k/XZ75UWmJ77ou5mfM1/0x7vP1ls9XQdF2z9uNsPzosXPNFA5m0/EX72TBSiqsWzN8z/GZB08pWq9VeEZ+0bjKb7RTD2i1P4u6r+bwypo5tZUumEcDAmuC3W8ezIqSGfE6g/sTd1W5p5bKjaWubrmWd29Fu9TD0GlYlmTx+8tTJoZeqYe2BZC1/JEU+wQR5TVEUPptJy3Fs+Vkzgf8lemqHumP1AnYoMZSwsVEz6o26i/G9Lgitb+ZmLu/YZtshfn5FZDPBCcJFQRQ+8ih9DctOFvdLIKHH6uUQnq9yhFu0bec7znZ+xpAGmuqef5/wd8hAyEDIQMjAETHwP7nQl2WnYk4yAAAAAElFTkSuQmCC'

    main()