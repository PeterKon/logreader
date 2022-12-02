import re
import os
from termcolor import colored
import PySimpleGUI as sg

#Log analysis

#TODO: Migrate to different GUI (maybe)
#TODO: Add support for several files in at once (maybe)
#TODO: Fix "limited" print when showing "error:" (all elements)
#TODO: Fix limit-variables to single var
#TODO: Implement general error-limit vs "error:" (add GUI)
#TODO: Optional "invalid", "failure", "illegal", "Exception:" and other current patterns opt
#TODO: Fix "Error:" being colored in "error" context

def name(name):

    NAME_SIZE = 23

    dots = NAME_SIZE-len(name)-2
    return sg.Text(name + ' ' + '•'*dots, size=(NAME_SIZE,1), justification='r',pad=(0,0), font='Courier 10')

def printArrayResults(arrIn, msg, limit, has_limit, context, gen_line, err_num):

    print("------------------------------------------------")
    print(gen_line)
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for i, x in enumerate(arrIn):
        regex_comp = re.split(r'([0-9]+ *->)', x, 1)
        if not (arrIn[i] == "-------->") and (msg.lower() in regex_comp[2].lower()):
            
            #Split into parts and print appropriate words in color. The format is simple:
            #1 - regex_comp[1] = The line-number in form "123  ->"
            #2 - rest_res[0]   = The string before the "error"-word
            #3 - warresword[0] = The error-word, retrieved to preserve case (ERROR: vs Error: etc)
            #4 - rest_res[1]   = The string after the "error"-word
            pattern = re.compile(re.escape(msg), re.IGNORECASE)
            warresword = re.findall(pattern, regex_comp[2])
            rest_res = re.split(pattern, regex_comp[2], 1)
            
            print(colored(regex_comp[1], "red", attrs=["bold"]) + colored(rest_res[0], 'green') + colored(warresword[0], "red") + colored(rest_res[1], 'green'))            
            err_count += 1
        else:
            #Colors the linenum-arrow
            first_split = re.split(r'([0-9]+ *->)', x, 1)            
            if(first_split[0] == "-------->"):
                print(x)
            else:
                print(colored(first_split[1], "blue", attrs=["bold"]) + first_split[2])
                
        if has_limit and (err_count == limit):
            
            #Print rest of context after error
            for h in range(context):
                if(((h + i) + 1) < len(arrIn)):
                    if msg.lower() in arrIn[(h + i) + 1].lower():
                        break
                    else:
                        res_split = re.split(r'([0-9]+ *->)', arrIn[(h + i) + 1], 1)
                        if(res_split[0] == "-------->"):
                            print(res_split[0])
                        else:
                            print(colored(res_split[1], "blue", attrs=["bold"]) + res_split[2])
                            
            insert_msg = "Limited, showing " + str(limit) + " out of " + str(err_num) + " elements.\n"
            print(colored(insert_msg, "blue", attrs=["bold"]))
            broken = True
            break
    if not broken:
        insert_msg = "Printed all " + str(err_num) + " elements.\n"
        print(colored(insert_msg, "blue", attrs=["bold"]))

def writeArrayResults(w, arrIn, limit, has_limit, gen_line, msg, err_num, context, write_to_file):

    err_count = 0
    broken = False
    
    if write_to_file:
        w.write("------------------------------------------------\n")
        w.write(gen_line + "\n")
        w.write("------------------------------------------------\n")
        for i, x in enumerate(arrIn):
            if msg.lower() in arrIn[i].lower():
                w.write(x + "\n")
                err_count += 1
            else:
                w.write(x + "\n")
            if has_limit and (err_count == limit):
                
                #Write rest of context after error
                for h in range(context):
                    if(((h + i) + 1) < len(arrIn)):
                        if msg.lower() in arrIn[(h + i) + 1].lower():
                            break
                        else:
                            w.write(arrIn[(h + i) + 1] + "\n")
                
                w.write("\nLimited, showing " + str(limit) + " out of " + str(err_num) + " elements.\n\n")
                broken = True
                break 
        if not broken:
            w.write("\nPrinted all " + str(err_num) + " elements.\n\n")

def addContextBefore(context_num, logoutput, in_arr, x):
    
    #Grabs messages before the error-line and adds them to array
    cont_num = context_num
    for z in range(context_num):
        if (cont_num >= 0):
            if(x - cont_num) >= 0:
                if(logoutput[x - cont_num] not in in_arr):
                    in_arr.append(logoutput[x - cont_num])
            cont_num += -1

def addContextAfter(context_num, logoutput, in_arr, x, msg, display_separator):

    #Grabs messages after the error-line and adds them to array
    for c in range(context_num):
        if((x + (c + 1)) > (len(logoutput) - 1)) or (msg in logoutput[x + (c + 1)].lower()):
            break
        in_arr.append(logoutput[x + (c + 1)])
            
    if display_separator:
        in_arr.append(" ")

def contextFixer(display_separator, in_arr):

    #This function looks for adjacent lines and checks if they are separated by
    #a line-separator, and removes the separator for adjacent lines only.
    #if not res triggers on a line-separator
    if display_separator:

        for x in range(len(in_arr)):
            
            res = in_arr[x].split()
            if not res:
                if(((x - 1) >= 0) and ((x + 1) < len(in_arr))):
                
                    comp1 = in_arr[x - 1].split()
                    comp1_res = re.search('[0-9]+', comp1[0]).group()
                    
                    comp2 = in_arr[x + 1].split()
                    comp2_res = re.search('[0-9]+', comp2[0]).group()
                    
                    if(int(comp1_res) == (int(comp2_res) - 1)):
                        in_arr[x] = "remove"
                        
        #Iterate backwards and remove unneeded lineseparators.
        v = len(in_arr) - 1
        for x in range(len(in_arr)):
            
            if(in_arr[v] == "remove"):
                in_arr.pop(v)
            v += -1
            
        for x in range(len(in_arr)):
            if(in_arr[x] == " "):
                in_arr[x] = "-------->"

def main():
    
    context = 3
    context_generic = 0
    
    display_separator = True
    display_separator_general = False
    write_to_file = True
    
    limit_output = 0
    limit_output_gen = 0
    limit_output_wargen = 0
    limit_output_failed = 0
    limit_output_fatal = 0
    
    general_limit = 0
    
    version = "Logreader v0.12"
    
    err_msg_arr = []
    errgen_msg_arr = []
    failgen_msg_arr = []
    fatalgen_msg_arr = []
    war_msg_arr = []
    cust_arr = []
    cust_arr2 = []
    cust_arr3 = []
    
    err_msg1 = "error:"    
    err_gen = "error"
    fail_gen = "failed"
    fatal_gen = "fatal"
    war_msg1 = "warning:"
    cust_pattern = ""
    cust_pattern2 = ""
    cust_pattern3 = ""
    
    #PySimpleGUI file-select
    layout = [[sg.T("")], 
        [sg.Text("Choose a logfile: "), 
            sg.Input(key="-IN2-" , change_submits=True), 
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
    def_toggle_size = (21,1)
    def_box_size = (21,1)
    
    layout = [
        [sg.Text('')],
        [sg.Text(('- Choose values -'))],
        [sg.Text(('Display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='SEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Write to file'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FILEWRITE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Output error limit:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='ERRIN', s=3),
            sg.Text("Default = Unlimited")],
        [sg.Text(('Context around errors:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='CONTIN', s=3),
            sg.Text("Default = 3")],
        [sg.Text('')],
        [sg.Text(('Custom pattern 1:'), size = def_box_size), sg.Input(key='CUSTOMIN', s=19)],
        [sg.Text(('Custom pattern 2:'), size = def_box_size), sg.Input(key='CUSTOMIN2', s=19)],
        [sg.Text(('Custom pattern 3:'), size = def_box_size), sg.Input(key='CUSTOMIN3', s=19)],
        [sg.Text('')],
        [sg.Text(('Generic display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='GENSEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('Generic context:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='GENCONTIN', s=3),
            sg.Text("Default = 0")],
        [sg.Text('')],
        [sg.Button("Submit")]
    ]
    
    window.close()    
    window = sg.Window(version, layout, size=(370,475))
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        elif event == 'SEPARATOR':
            window['SEPARATOR'].metadata = not window['SEPARATOR'].metadata
            window['SEPARATOR'].update(image_data=toggle_btn_on if window['SEPARATOR'].metadata else toggle_btn_off)
            display_separator = window['SEPARATOR'].metadata
        elif event == 'GENSEPARATOR':
            window['GENSEPARATOR'].metadata = not window['GENSEPARATOR'].metadata
            window['GENSEPARATOR'].update(image_data=toggle_btn_on if window['GENSEPARATOR'].metadata else toggle_btn_off)
            display_separator_general = window['GENSEPARATOR'].metadata
        elif event == 'FILEWRITE':
            window['FILEWRITE'].metadata = not window['FILEWRITE'].metadata
            window['FILEWRITE'].update(image_data=toggle_btn_on if window['FILEWRITE'].metadata else toggle_btn_off)
            write_to_file = window['FILEWRITE'].metadata
        elif event == 'CUSTOMIN':
            cust_pattern = values['CUSTOMIN']
        elif event == 'CUSTOMIN2':
            cust_pattern2 = values['CUSTOMIN2']
        elif event == 'CUSTOMIN3':
            cust_pattern3 = values['CUSTOMIN3']
        elif event == "Submit":
            display_separator = window['SEPARATOR'].metadata
            write_to_file = window['FILEWRITE'].metadata
            display_separator_general = window['GENSEPARATOR'].metadata
            cust_pattern = values['CUSTOMIN']
            cust_pattern2 = values['CUSTOMIN2']
            cust_pattern3 = values['CUSTOMIN3']
            
            if values['GENCONTIN'] != '':
                context_generic = int(values['GENCONTIN'])
            
            if values['ERRIN'] != '':
                general_limit = int(values['ERRIN'])
                
            if values['CONTIN'] != '':
                context = int(values['CONTIN'])
                
            break
            
        elif event == 'ERRIN' and len(values['ERRIN']) and values['ERRIN'][-1] not in ('0123456789'):
            window['ERRIN'].update(values['ERRIN'][:-1])
        elif event == 'CONTIN' and len(values['CONTIN']) and values['CONTIN'][-1] not in ('0123456789'):
            window['CONTIN'].update(values['CONTIN'][:-1])
        elif event == 'GENCONTIN' and len(values['GENCONTIN']) and values['GENCONTIN'][-1] not in ('0123456789'):
            window['GENCONTIN'].update(values['GENCONTIN'][:-1])
    window.close()
    
    custIsInitiated = (cust_pattern != "")
    custIsInitiated2 = (cust_pattern2 != "")
    custIsInitiated3 = (cust_pattern3 != "")
    
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

    #Reading
    f = open(filename, "r")
    if write_to_file:
        w = open("outfile.txt", "w")
        
    logoutput = f.read().splitlines()
    
    #Formatting each line to the format 123xxxx-> where x is spaces and maintaining the same
    #num of spaces up to 8 digits to make them line up.
    for x in range(len(logoutput)):

        space_string = ""
        num_len = len(str(x + 1))
        
        if x >= 0:
            for z in range(7-(num_len)):
                space_string += " "
        
        logoutput[x] = str(x + 1) + space_string + "-> " + logoutput[x]
    
    #Appending the error-strings to the appropriate array, and adding context
    err_num = 0
    err_gen_num = 0
    war_gen_num = 0
    fail_gen_num = 0
    fatal_gen_num = 0
    cust_arr_num = 0
    cust_arr_num2 = 0
    cust_arr_num3 = 0
    for x in range(len(logoutput)):
        
        #Add errors in format "error:"
        if (err_msg1 in logoutput[x].lower()):
            
            addContextBefore(context, logoutput, err_msg_arr, x)
            err_msg_arr.append(logoutput[x])
            err_num +=1
            addContextAfter(context, logoutput, err_msg_arr, x, "error:", display_separator)
        
        #Add the other generic messages
        if (war_msg1 in logoutput[x].lower()):
            
            addContextBefore(context_generic, logoutput, war_msg_arr, x)
            war_msg_arr.append(logoutput[x])
            war_gen_num +=1
            addContextAfter(context_generic, logoutput, war_msg_arr, x, war_msg1, display_separator_general)
            
        if (err_gen in logoutput[x].lower()) and ("error:" not in logoutput[x].lower()):
        
            addContextBefore(context_generic, logoutput, errgen_msg_arr, x)
            errgen_msg_arr.append(logoutput[x])
            err_gen_num +=1
            addContextAfter(context_generic, logoutput, errgen_msg_arr, x, err_gen, display_separator_general)
            
        if (fail_gen in logoutput[x].lower()):
            
            addContextBefore(context_generic, logoutput, failgen_msg_arr, x)
            failgen_msg_arr.append(logoutput[x])
            fail_gen_num +=1
            addContextAfter(context_generic, logoutput, failgen_msg_arr, x, fail_gen, display_separator_general)
            
        if (fatal_gen in logoutput[x].lower()):
            
            addContextBefore(context_generic, logoutput, fatalgen_msg_arr, x)
            fatalgen_msg_arr.append(logoutput[x])
            fatal_gen_num +=1
            addContextAfter(context_generic, logoutput, fatalgen_msg_arr, x, fatal_gen, display_separator_general)
            
        if custIsInitiated:
            regex_comp = re.split(r'([0-9]+ *->)', logoutput[x], 1)
            if (cust_pattern.lower() in regex_comp[2].lower()):
                addContextBefore(context_generic, logoutput, cust_arr, x)
                cust_arr.append(logoutput[x])
                cust_arr_num +=1
                addContextAfter(context_generic, logoutput, cust_arr, x, cust_pattern, display_separator_general)
                
        if custIsInitiated2:
            regex_comp = re.split(r'([0-9]+ *->)', logoutput[x], 1)
            if (cust_pattern2.lower() in regex_comp[2].lower()):
                
                addContextBefore(context_generic, logoutput, cust_arr2, x)
                cust_arr2.append(logoutput[x])
                cust_arr_num2 +=1
                addContextAfter(context_generic, logoutput, cust_arr2, x, cust_pattern2, display_separator_general)
                
        if custIsInitiated3:
            regex_comp = re.split(r'([0-9]+ *->)', logoutput[x], 1)
            if (cust_pattern3.lower() in regex_comp[2].lower()):
                
                addContextBefore(context_generic, logoutput, cust_arr3, x)
                cust_arr3.append(logoutput[x])
                cust_arr_num3 +=1
                addContextAfter(context_generic, logoutput, cust_arr3, x, cust_pattern3, display_separator_general)
                

    #Checking for spaces that we dont need (places where separating errors do not make sense)        
    contextFixer(display_separator, err_msg_arr)
    contextFixer(display_separator_general, errgen_msg_arr)
    contextFixer(display_separator_general, war_msg_arr)
    contextFixer(display_separator_general, failgen_msg_arr)
    contextFixer(display_separator_general, fatalgen_msg_arr)
    if custIsInitiated:
        contextFixer(display_separator_general, cust_arr)
    if custIsInitiated2:
        contextFixer(display_separator_general, cust_arr2)
    if custIsInitiated3:
        contextFixer(display_separator_general, cust_arr3)
    
    #Print results
    print("\n" + version + "\n")
    print("Filename:\n" + filename + "\n")
    print("Number of errors in this file:           " + str(err_num))
    print("Number of generic errors in this file:   " + str(err_gen_num))
    print("Number of warnings in this file:         " + str(war_gen_num))
    print("Number of generic failures in this file: " + str(fail_gen_num))
    print("Number of generic fatals in this file:   " + str(fatal_gen_num))
    if custIsInitiated:
        print()
        print("Custom pattern: " + cust_pattern)
        print("Hits on pattern:                         " + str(cust_arr_num))
    if custIsInitiated2:
        print()
        print("Custom pattern: " + cust_pattern2)
        print("Hits on pattern:                         " + str(cust_arr_num2))
    if custIsInitiated3:
        print()
        print("Custom pattern: " + cust_pattern3)
        print("Hits on pattern:                         " + str(cust_arr_num3))
    print()
    print("Printed with context of:                 " + str(context))
    print("Lines in file:                           " + str(len(logoutput)))
    print()
    
    #Write to file
    if write_to_file:
        w.write("\n" + version + "\n\n")
        w.write("Filename:\n" + filename + "\n\n")
        w.write("Number of errors in this file:           " + str(err_num) + "\n")
        w.write("Number of generic errors in this file:   " + str(err_gen_num) + "\n")
        w.write("Number of warnings in this file:         " + str(war_gen_num) + "\n")
        w.write("Number of generic failures in this file: " + str(fail_gen_num) + "\n")
        w.write("Number of generic fatals in this file:   " + str(fatal_gen_num) + "\n")
        if custIsInitiated:
            w.write("\nCustom pattern: " + cust_pattern + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num) + "\n")
        if custIsInitiated2:
            w.write("\nCustom pattern: " + cust_pattern2 + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num2) + "\n")
        if custIsInitiated3:
            w.write("\nCustom pattern: " + cust_pattern3 + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num3) + "\n")
        w.write("\n")
        w.write("Printed with context of:                 " + str(context) + "\n")
        w.write("Lines in file:                           " + str(len(logoutput)) + "\n")
        w.write("\n")

    os.system('color')
    
    generr_line = "Errors contained:                              |"
    printArrayResults(err_msg_arr, err_msg1, limit_output, has_limit, context, generr_line, err_num)    
    writeArrayResults(w, err_msg_arr, limit_output, has_limit, generr_line, err_msg1, err_num, context, write_to_file)
    
    generr_line = "Generic errors contained:                      |"
    printArrayResults(errgen_msg_arr, err_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, err_gen_num)
    writeArrayResults(w, errgen_msg_arr, limit_output_gen, has_limit_gen, generr_line, err_gen, err_gen_num, context_generic, write_to_file)
    
    generr_line = "Warnings contained:                            |"
    printArrayResults(war_msg_arr, war_msg1, limit_output_wargen, has_limit_wargen, context_generic, generr_line, war_gen_num)
    writeArrayResults(w, war_msg_arr, limit_output_wargen, has_limit_wargen, generr_line, war_msg1, war_gen_num, context_generic, write_to_file)
            
    generr_line = "Generic failures contained:                    |"
    printArrayResults(failgen_msg_arr, fail_gen, limit_output_failed, has_limit_failed, context_generic, generr_line, fail_gen_num)
    writeArrayResults(w, failgen_msg_arr, limit_output_failed, has_limit_failed, generr_line, fail_gen, fail_gen_num, context_generic, write_to_file)
            
    generr_line = "Generic fatals contained:                      |"
    printArrayResults(fatalgen_msg_arr, fatal_gen, limit_output_fatal, has_limit_fatal, context_generic, generr_line, fatal_gen_num)
    writeArrayResults(w, fatalgen_msg_arr, limit_output_fatal, has_limit_fatal, generr_line, fatal_gen, fatal_gen_num, context_generic, write_to_file)
        
    if custIsInitiated:
        generr_line = "Pattern searched: " + cust_pattern
        printArrayResults(cust_arr, cust_pattern, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num)
        writeArrayResults(w, cust_arr, limit_output_gen, has_limit_gen, generr_line, cust_pattern, cust_arr_num, context_generic, write_to_file)
            
    if custIsInitiated2:
        generr_line = "Pattern searched: " + cust_pattern2
        printArrayResults(cust_arr2, cust_pattern2, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num2)
        writeArrayResults(w, cust_arr2, limit_output_gen, has_limit_gen, generr_line, cust_pattern2, cust_arr_num2, context_generic, write_to_file)
            
    if custIsInitiated3:
        generr_line = "Pattern searched: " + cust_pattern3
        printArrayResults(cust_arr3, cust_pattern3, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num3)
        writeArrayResults(w, cust_arr3, limit_output_gen, has_limit_gen, generr_line, cust_pattern3, cust_arr_num3, context_generic, write_to_file)
        
    f.close()
    if write_to_file:
        w.close()    

if __name__ == "__main__":

    toggle_btn_off = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAED0lEQVRYCe1WTWwbRRR+M/vnv9hO7BjHpElMKSlpqBp6gRNHxAFVcKM3qgohQSqoqhQ45YAILUUVDRxAor2VAweohMSBG5ciodJUSVqa/iikaePEP4nj2Ovdnd1l3qqJksZGXscVPaylt7Oe/d6bb9/svO8BeD8vA14GvAx4GXiiM0DqsXv3xBcJU5IO+RXpLQvs5yzTijBmhurh3cyLorBGBVokQG9qVe0HgwiXLowdy9aKsY3g8PA5xYiQEUrsk93JTtjd1x3siIZBkSWQudUK4nZO1w3QuOWXV+HuP/fL85klAJuMCUX7zPj4MW1zvC0Ej4yMp/w++K2rM9b70sHBYCjo34x9bPelsgp/XJksZ7KFuwZjr3732YcL64ttEDw6cq5bVuCvgy/sje7rT0sI8PtkSHSEIRIKgCQKOAUGM6G4VoGlwiqoVd2Za9Vl8u87bGJqpqBqZOj86eEHGNch+M7otwHJNq4NDexJD+59RiCEQG8qzslFgN8ibpvZNsBifgXmFvJg459tiOYmOElzYvr2bbmkD509e1ylGEZk1Y+Ssfan18n1p7vgqVh9cuiDxJPxKPT3dfGXcN4Tp3dsg/27hUQs0qMGpRMYjLz38dcxS7Dm3nztlUAb38p0d4JnLozPGrbFfBFm79c8hA3H2AxcXSvDz7/+XtZE1kMN23hjV7LTRnKBh9/cZnAj94mOCOD32gi2EUw4FIRUMm6LGhyiik86nO5NBdGRpxYH14bbjYfJteN/OKR7UiFZVg5T27QHYu0RBxoONV9W8KQ7QVp0iXdE8fANUGZa0QAvfhhXlkQcmjJZbt631oIBnwKmacYoEJvwiuFgWncWnXAtuVBBEAoVVXWCaQZzxmYuut68b631KmoVBEHMUUrJjQLXRAQVSxUcmrKVHfjWWjC3XOT1FW5QrWpc5IJdQhDKVzOigEqS5dKHMVplnNOqrmsXqUSkn+YzWaHE9RW1FeXL7SKZXBFUrXW6jIV6YTEvMAUu0W/G3kcxPXP5ylQZs4fa6marcWvvZfJu36kuHjlc/nMSuXz+/ejxgqPFpuQ/xVude9eu39Jxu27OLvBGoMjrUN04zrNMbgVmOBZ96iPdPZmYntH5Ls76KuxL9NyoLA/brav7n382emDfHqeooXyhQmARVhSnAwNNMx5bu3V1+habun5nWdXhwJZ2C5mirTesyUR738sv7g88UQ0rEkTDlp+1wwe8Pf0klegUenYlgyg7bby75jUTITs2rhCAXXQ2vwxz84vlB0tZ0wL4NEcLX/04OrrltG1s8aOrHhk51SaK0us+n/K2xexBxljcsm1n6x/Fuv1PCWGiKOaoQCY1Vb9gWPov50+fdEqd21ge3suAlwEvA14G/ucM/AuppqNllLGPKwAAAABJRU5ErkJggg=='
    toggle_btn_on = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAD+UlEQVRYCe1XzW8bVRCffbvrtbP+2NhOD7GzLm1VoZaPhvwDnKBUKlVyqAQ3/gAkDlWgPeVQEUCtEOIP4AaHSI0CqBWCQyXOdQuRaEFOk3g3IMWO46+tvZ+PeZs6apq4ipON1MNafrvreTPzfvub92bGAOEnZCBkIGQgZOClZoDrh25y5pdjruleEiX+A+rCaQo05bpuvJ/+IHJCSJtwpAHA/e269g8W5RbuzF6o7OVjF8D3Pr4tSSkyjcqfptPDMDKSleW4DKIggIAD5Yf+Oo4DNg6jbUBlvWLUNutAwZu1GnDjzrcXzGcX2AHw/emFUV6Sfk0pqcKpEydkKSo9q3tkz91uF5aWlo1Gs/mYc+i7tz4//19vsW2AU9O381TiioVCQcnlRsWeQhD3bJyH1/MiFLICyBHiuzQsD1arDvypW7DR9nzZmq47q2W95prm+I9fXfqXCX2AF2d+GhI98Y8xVX0lnxvl2UQQg0csb78ag3NjEeD8lXZ7pRTgftmCu4864OGzrq+5ZU0rCa3m+NzXlzvoAoB3+M+SyWQuaHBTEzKMq/3BMbgM+FuFCDBd9kK5XI5PJBKqLSev+POTV29lKB8rT0yMD0WjUSYLZLxzNgZvIHODOHuATP72Vwc6nQ4Uiw8MUeBU4nHS5HA6TYMEl02wPRcZBJuv+ya+UCZOIBaLwfCwQi1Mc4QXhA+PjWRkXyOgC1uIhW5Qd8yG2TK7kSweLcRGKKVnMNExWWBDTQsH9qVmtmzjiThQDs4Qz/OUSGTwcLwIQTLW58i+yOjpXDLqn1tgmDzXzRCk9eDenjo9yhvBmlizrB3V5dDrNTuY0A7opdndStqmaQLPC1WCGfShYRgHdLe32UrV3ntiH9LliuNrsToNlD4kruN8v75eafnSgC6Luo2+B3fGKskilj5muV6pNhk2Qqg5v7lZ51nBZhNBjGrbxfI1+La5t2JCzfD8RF1HTBGJXyDzs1MblONulEqPDVYXgwDIfNx91IUVbAbY837GMur+/k/XZ75UWmJ77ou5mfM1/0x7vP1ls9XQdF2z9uNsPzosXPNFA5m0/EX72TBSiqsWzN8z/GZB08pWq9VeEZ+0bjKb7RTD2i1P4u6r+bwypo5tZUumEcDAmuC3W8ezIqSGfE6g/sTd1W5p5bKjaWubrmWd29Fu9TD0GlYlmTx+8tTJoZeqYe2BZC1/JEU+wQR5TVEUPptJy3Fs+Vkzgf8lemqHumP1AnYoMZSwsVEz6o26i/G9Lgitb+ZmLu/YZtshfn5FZDPBCcJFQRQ+8ih9DctOFvdLIKHH6uUQnq9yhFu0bec7znZ+xpAGmuqef5/wd8hAyEDIQMjAETHwP7nQl2WnYk4yAAAAAElFTkSuQmCC'

    main()